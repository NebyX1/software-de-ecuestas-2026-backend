"""Server validation: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/."""
import requests
from flask import current_app

from .survey_errors import SurveyError


def verify_turnstile(token):
    if not current_app.config.get('TURNSTILE_REQUIRED', True):
        return
    if not token:
        raise SurveyError('captcha_required', 'Completá la verificación de seguridad.')
    try:
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': current_app.config['TURNSTILE_SECRET_KEY'], 'response': token},
            timeout=(3, 8),
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError, KeyError):
        raise SurveyError('service_unavailable', 'No se pudo verificar la seguridad. Intentá nuevamente.', 503)
    if not isinstance(result, dict):
        raise SurveyError('service_unavailable', 'No se pudo verificar la seguridad. Intentá nuevamente.', 503)
    if (result.get('success') is not True
            or result.get('hostname') != current_app.config.get('TURNSTILE_HOSTNAME')
            or result.get('action') != 'survey_start'):
        raise SurveyError('captcha_invalid', 'La verificación venció o no es válida. Volvé a completarla.')
