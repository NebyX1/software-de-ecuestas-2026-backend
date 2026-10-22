"""Descriptive telemetry, inferred from UA and bounded client hints.

Never used for authentication, uniqueness claims or submission idempotency.
No raw UA, hardware identifiers or complete fingerprint is persisted.
"""
import re
from ua_parser import parse

DEVICE_OPTIONS = {'mobile': 'Celular', 'tablet': 'Tablet', 'desktop': 'Computadora', 'other': 'Otro', 'unknown': 'No detectado'}
OS_OPTIONS = {'android': 'Android', 'ios': 'iOS / iPadOS', 'windows': 'Windows', 'macos': 'macOS', 'linux': 'Linux', 'chromeos': 'ChromeOS', 'other': 'Otro', 'unknown': 'No detectado'}
BROWSER_OPTIONS = {'chrome': 'Chrome / Chromium', 'edge': 'Edge', 'firefox': 'Firefox', 'safari': 'Safari', 'samsung': 'Samsung Internet', 'opera': 'Opera', 'facebook': 'Facebook', 'instagram': 'Instagram', 'other': 'Otro', 'unknown': 'No detectado'}
CONTEXT_OPTIONS = {'browser': 'Navegador', 'facebook': 'Facebook', 'instagram': 'Instagram', 'webview': 'Otro navegador integrado', 'unknown': 'No detectado'}
METADATA_FILTERS = {
    'device_type': {'label': 'Tipo de dispositivo', 'options': DEVICE_OPTIONS},
    'os_family': {'label': 'Sistema operativo', 'options': OS_OPTIONS},
    'browser_family': {'label': 'Navegador', 'options': BROWSER_OPTIONS},
    'browser_context': {'label': 'Aplicación de acceso', 'options': CONTEXT_OPTIONS},
}
METADATA_FIELDS = {
    'device_type': 'Tipo de dispositivo', 'device_brand': 'Marca', 'device_model': 'Modelo informado',
    'os_family': 'Sistema operativo', 'os_version': 'Versión del sistema informada',
    'browser_family': 'Navegador', 'browser_name': 'Nombre informado del navegador',
    'browser_version': 'Versión del navegador informada', 'browser_context': 'Aplicación de acceso',
    'language': 'Idioma', 'timezone': 'Zona horaria', 'screen_width': 'Ancho de pantalla (px CSS)',
    'screen_height': 'Alto de pantalla (px CSS)', 'viewport_width': 'Ancho de ventana (px CSS)',
    'viewport_height': 'Alto de ventana (px CSS)', 'pixel_ratio': 'Densidad de píxeles',
    'touch_points': 'Puntos táctiles informados', 'source': 'Fuente de detección',
}


def _text(value, limit=128):
    return re.sub(r'[\x00-\x1f\x7f]', '', value or '').strip()[:limit] or None


def _version(value):
    if value is None:
        return None
    return '.'.join(str(part) for part in (value.major, value.minor, value.patch, value.patch_minor) if part is not None) or None


def _os_family(value):
    name = (value or '').lower()
    if name == 'android': return 'android'
    if name in ('ios', 'ipados'): return 'ios'
    if name == 'windows': return 'windows'
    if name in ('mac os x', 'macos'): return 'macos'
    if name in ('chrome os', 'chromeos', 'chromium os'): return 'chromeos'
    if name in ('linux', 'ubuntu', 'debian', 'fedora', 'linux mint'): return 'linux'
    return 'other' if name and name != 'other' else 'unknown'


def _browser_family(name):
    name = (name or '').lower()
    for needle, family in (('instagram', 'instagram'), ('facebook', 'facebook'), ('edge', 'edge'), ('opera', 'opera'), ('samsung', 'samsung'), ('firefox', 'firefox'), ('chrome', 'chrome'), ('chromium', 'chrome'), ('safari', 'safari')):
        if needle in name: return family
    return 'other' if name and name != 'other' else 'unknown'


def capture_device_metadata(user_agent, reported):
    # Parsing is bounded even for direct API clients with enormous UA headers.
    ua = _text(user_agent, 1024) or ''
    parsed = parse(ua)
    hints = reported.get('clientHints', {})
    os_name = parsed.os.family if parsed.os else None
    os_family = _os_family(os_name)
    os_version = _version(parsed.os)
    browser_name = parsed.user_agent.family if parsed.user_agent else None
    browser_version = _version(parsed.user_agent)
    brand = _text(parsed.device.brand) if parsed.device else None
    model = _text(parsed.device.model) if parsed.device else None
    if brand and (brand.lower().startswith('generic') or brand == 'Other'):
        brand = None
    if model in ('K', 'Other', 'Generic Smartphone', 'Generic Tablet'): model = None
    used_hints = False
    hinted_platform = hints.get('platform', '')
    if _os_family(hinted_platform) not in ('unknown', 'other'):
        os_family = _os_family(hinted_platform)
        used_hints = True
        platform_version = hints.get('platformVersion', '')
        if platform_version:
            if os_family == 'windows':
                major = int(platform_version.split('.')[0] or '0')
                # Windows UA-CH uses UniversalApiContract versions, not OS versions.
                os_version = '11 o posterior' if major >= 13 else '10' if major > 0 else None
            else:
                os_version = platform_version
        elif os_family != _os_family(os_name):
            os_version = None
    if os_family == 'windows' and not hints.get('platformVersion') and os_version == '10':
        os_version = '10 / 11 (no distinguible)'
    if os_family == 'android' and re.search(r'Android 10; K\)', ua) and not hints.get('platformVersion'):
        os_version = None  # Reduced UA placeholder, not the actual Android version.
    if _text(hints.get('model')):
        model = _text(hints['model'])
        used_hints = True
    if model and not brand:
        if model.startswith('SM-'): brand = 'Samsung'
        elif model.startswith('Pixel'): brand = 'Google'
    for browser in sorted(hints.get('fullVersionList', []) or hints.get('brands', []),
                          key=lambda entry: {'Microsoft Edge': 0, 'Opera': 1, 'Google Chrome': 2, 'Chromium': 3}.get(entry['brand'], 99)):
        if browser['brand'] in ('Microsoft Edge', 'Opera', 'Google Chrome', 'Chromium'):
            # Embedded app names from the UA remain visible instead of being lost.
            if _browser_family(browser_name) not in ('facebook', 'instagram'):
                browser_name, browser_version = browser['brand'], browser['version']
                used_hints = True
            break
    if 'Instagram' in ua: context = 'instagram'
    elif re.search(r'FBAN/|FBAV/|FB_IAB/', ua): context = 'facebook'
    elif re.search(r'; wv\)|WebView', ua, re.I): context = 'webview'
    else: context = 'browser' if browser_name else 'unknown'
    ipad_desktop = os_family == 'macos' and reported.get('touchPoints', 0) > 1
    if ipad_desktop:
        os_family, os_version, brand, model = 'ios', None, 'Apple', 'iPad (estimado)'
    if ipad_desktop or re.search(r'iPad|Tablet', ua, re.I) or (os_family == 'android' and 'Mobile' not in ua and hints.get('mobile') is not True):
        device_type = 'tablet'
    elif hints.get('mobile') is True or re.search(r'iPhone|iPod|Mobile|Windows Phone', ua, re.I):
        device_type = 'mobile'
    elif os_family in ('windows', 'macos', 'linux', 'chromeos'):
        device_type = 'desktop'
    else:
        device_type = 'unknown'
    result = {
        'version': 1, 'device_type': device_type, 'device_brand': brand, 'device_model': model,
        'os_family': os_family, 'os_version': _text(os_version, 64),
        'browser_family': _browser_family(browser_name), 'browser_name': _text(browser_name, 64),
        'browser_version': _text(browser_version, 32), 'browser_context': context,
        'source': 'client_hints_and_user_agent' if used_hints else 'user_agent' if ua else 'not_available',
        'language': _text(reported.get('language'), 64), 'timezone': _text(reported.get('timezone'), 64),
        'pixel_ratio': reported.get('pixelRatio'), 'touch_points': reported.get('touchPoints'),
    }
    for name in ('screen', 'viewport'):
        for dimension in ('width', 'height'):
            result[f'{name}_{dimension}'] = reported.get(name, {}).get(dimension)
    return result


def metadata_display_values(response):
    metadata = response.device_metadata or {}
    options = {key: value['options'] for key, value in METADATA_FILTERS.items()}
    options['source'] = {'client_hints_and_user_agent': 'Encabezado del navegador y datos adicionales',
                         'user_agent': 'Encabezado del navegador', 'not_available': 'No disponible'}
    return [(label, options[key].get(metadata.get(key), 'No disponible')
             if key in options else metadata.get(key)) for key, label in METADATA_FIELDS.items()]
