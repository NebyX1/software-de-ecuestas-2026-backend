import hashlib
import hmac
import ipaddress
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import current_app, request
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.extensions import db
from app.models.survey import SurveyInvitation, SurveyResponse
from app.repositories.survey import add_claims, add_values, has_claims, invitation_by_hash
from app.schemas.survey import normalize_phone
from .antibot_service import verify_turnstile
from .challenge_service import consume_challenge
from .survey_errors import SurveyError
from .device_metadata import capture_device_metadata

BROWSER_COOKIE = 'survey_browser'


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(kind, value):
    key = current_app.config['IDENTITY_HMAC_KEY'].encode()
    message = f"{current_app.config['SURVEY_ID']}\0{kind}\0{value}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _cookie_signer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='survey-browser-v1')


def _browser_id(create=False):
    raw = request.cookies.get(BROWSER_COOKIE, '')
    if raw:
        try:
            value = _cookie_signer().loads(raw)
            if isinstance(value, str) and len(value) == 43:
                return value, None
        except BadSignature:
            pass
    if not create:
        raise SurveyError('link_bound', 'Este enlace está vinculado al navegador que inició la encuesta.', 403)
    value = secrets.token_urlsafe(32)
    return value, _cookie_signer().dumps(value)


def _ip_digest():
    try:
        address = ipaddress.ip_address(request.remote_addr or '')
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        # Rotating IPv6 privacy addresses in one LAN retain the same /64 key.
        bucket = str(ipaddress.ip_network(f'{address}/64', strict=False)) if address.version == 6 else str(address)
        return digest('ip', bucket)
    except ValueError:
        raise SurveyError('service_unavailable', 'No se pudo validar el origen de la conexión.', 503)


def _claims(device_hash, browser_hash, phone_hash=None):
    claims = {'device': device_hash, 'browser': browser_hash}
    if current_app.config.get('SURVEY_ENFORCE_IP_UNIQUENESS', False):
        claims['ip'] = _ip_digest()
    if phone_hash:
        claims['phone'] = phone_hash
    return claims


def create_link(data):
    browser, cookie = _browser_id(create=True)
    device_hash = digest('device', data['deviceId'].lower())
    browser_hash = digest('browser', browser)
    if has_claims(_claims(device_hash, browser_hash)):
        raise SurveyError('duplicate_response', 'Ya se registró una participación desde este dispositivo o conexión.', 409)
    verify_turnstile(data.get('turnstileToken'))
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=current_app.config.get('SURVEY_TOKEN_TTL_SECONDS', 86400))
    invitation = SurveyInvitation(
        survey_id=current_app.config['SURVEY_ID'], token_hash=digest('token', token),
        device_hash=device_hash, browser_hash=browser_hash, ip_hash=_ip_digest(),
        expires_at=expires, attribution=data.get('attribution', {}),
    )
    db.session.add(invitation)
    db.session.commit()
    return {'token': token, 'expiresAt': expires.isoformat() + 'Z'}, cookie


def owned_invitation(data, *, lock=False, allow_consumed=False):
    invitation = invitation_by_hash(digest('token', data['token']), lock=lock)
    if not invitation:
        raise SurveyError('link_invalid', 'El enlace de la encuesta no es válido.', 404)
    try:
        browser, _ = _browser_id()
    except SurveyError:
        if invitation.consumed_at:
            raise SurveyError('link_used', 'Este enlace ya fue utilizado y no admite otra respuesta.', 409)
        raise
    device_hash = digest('device', data['deviceId'].lower())
    browser_hash = digest('browser', browser)
    if not (hmac.compare_digest(invitation.device_hash, device_hash)
            and hmac.compare_digest(invitation.browser_hash, browser_hash)):
        if invitation.consumed_at:
            raise SurveyError('link_used', 'Este enlace ya fue utilizado y no admite otra respuesta.', 409)
        raise SurveyError('link_bound', 'Este enlace está vinculado al navegador que inició la encuesta.', 403)
    if invitation.consumed_at:
        if allow_consumed:
            return invitation
        raise SurveyError('link_used', 'Este enlace ya fue utilizado y no admite otra respuesta.', 409)
    if invitation.expires_at <= utcnow():
        raise SurveyError('link_expired', 'El enlace de la encuesta venció. Volvé al enlace de la campaña.', 410)
    return invitation


def session_status(data):
    invitation = owned_invitation(data, allow_consumed=True)
    result = {'status': 'completed' if invitation.consumed_at else 'active',
              'expiresAt': invitation.expires_at.isoformat() + 'Z'}
    if invitation.consumed_at:
        result['receiptId'] = invitation.receipt_id
    return result


def _submission_hash(data, phone_hash):
    content = {'answers': data['answers'], 'phone': phone_hash, 'consentVersion': data['consentVersion']}
    return digest('submission', json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':')))


def submit_response(data):
    if data.get('website', ''):
        raise SurveyError('submission_rejected', 'No pudimos validar el envío. Revisá el formulario e intentá nuevamente.', 400)
    phone_hash = digest('phone', normalize_phone(data['phone']))
    content_hash = _submission_hash(data, phone_hash)
    challenge_consumed = False
    for attempt in range(3):
        try:
            invitation = owned_invitation(data, lock=True, allow_consumed=True)
            if invitation.consumed_at:
                if hmac.compare_digest(invitation.submission_hash or '', content_hash):
                    return {'status': 'completed', 'receiptId': invitation.receipt_id}, 200
                raise SurveyError('link_used', 'Este enlace ya fue utilizado y no admite otra respuesta.', 409)
            elapsed = (utcnow() - invitation.created_at).total_seconds()
            minimum = current_app.config.get('SURVEY_MIN_FILL_SECONDS', 15)
            if elapsed < minimum:
                wait = max(1, int(minimum - elapsed + 1))
                raise SurveyError('submission_too_fast', f'Esperá {wait} segundos y revisá tus respuestas antes de enviar.', 429)
            claims = _claims(invitation.device_hash, invitation.browser_hash, phone_hash)
            if has_claims(claims):
                raise SurveyError('duplicate_response', 'Ya se registró una participación con estos datos.', 409)
            # Hold the invitation row lock before consuming Redis. Identical
            # concurrent retries observe the committed receipt above and never
            # consume a second challenge. A DB deadlock retry in THIS request
            # keeps the already-validated state; a new request needs a new
            # verifier if the transaction could not be persisted.
            if not challenge_consumed:
                consume_challenge(invitation, data['challengeId'], data['challengeAnswer'])
                challenge_consumed = True
            now, receipt = utcnow(), str(uuid4())
            # Conditional UPDATE makes consumption atomic even on SQLite where
            # SELECT FOR UPDATE is ignored; MariaDB additionally holds the row lock.
            updated = db.session.execute(update(SurveyInvitation).where(
                SurveyInvitation.id == invitation.id, SurveyInvitation.consumed_at.is_(None),
            ).values(consumed_at=now, receipt_id=receipt, submission_hash=content_hash))
            if updated.rowcount != 1:
                db.session.rollback()
                continue
            add_claims(claims)
            metadata = capture_device_metadata(request.headers.get('User-Agent', ''), data.get('clientMetadata', {}))
            opinion = SurveyResponse(
                id=str(uuid4()), survey_id=current_app.config['SURVEY_ID'], answers=data['answers'],
                consent_version=data['consentVersion'], consented_at=now, created_at=now,
                device_metadata=metadata, device_type=metadata['device_type'],
                os_family=metadata['os_family'], browser_family=metadata['browser_family'],
                browser_context=metadata['browser_context'],
            )
            db.session.add(opinion)
            db.session.flush()
            add_values(opinion)
            db.session.commit()
            return {'status': 'completed', 'receiptId': receipt}, 201
        except IntegrityError:
            db.session.rollback()
            # Competing workers might have committed this exact submission.
            invitation = owned_invitation(data, allow_consumed=True)
            if invitation.consumed_at and hmac.compare_digest(invitation.submission_hash or '', content_hash):
                return {'status': 'completed', 'receiptId': invitation.receipt_id}, 200
            raise SurveyError('duplicate_response', 'Ya se registró una participación con estos datos.', 409)
        except OperationalError as exc:
            db.session.rollback()
            # MariaDB deadlock (1213) or lock wait timeout (1205): retry the whole
            # transaction. Other DB errors fail closed and are handled upstream.
            args = getattr(exc.orig, 'args', ())
            code = args[0] if args else None
            if code not in (1205, 1213) or attempt == 2:
                raise
    raise SurveyError('submission_busy', 'El envío está en curso. Intentá nuevamente.', 409)


def purge_invitation_metadata():
    """Keep durable duplicate claims; discard expired invitation metadata.

    The 24h receipt retry window is intentionally shorter than claim retention.
    Run daily; losing an old receipt does not enable another response.
    """
    now = utcnow()
    consumed_before = now - timedelta(hours=24)
    removed = SurveyInvitation.query.filter(
        ((SurveyInvitation.consumed_at.is_(None)) & (SurveyInvitation.expires_at < now))
        | (SurveyInvitation.consumed_at < consumed_before)
    ).delete(synchronize_session=False)
    db.session.commit()
    return {'invitations_deleted': removed}
