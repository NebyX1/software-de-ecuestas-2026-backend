"""Canonical connection address shared by real and simulated submissions."""
import ipaddress

from flask import request

from app.services.survey_errors import SurveyError


def client_ip_address():
    """Use the server address after the configured trusted proxy middleware."""
    try:
        address = ipaddress.ip_address(request.remote_addr or '')
        if address.version == 6:
            if address.scope_id is not None:
                raise ValueError('Scoped IPv6 addresses are not accepted')
            if address.ipv4_mapped:
                address = address.ipv4_mapped
        return str(address)
    except ValueError:
        raise SurveyError('service_unavailable', 'No se pudo validar el origen de la conexión.', 503)
