from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from .security import ApiCSRFProtect
from .services.mail_service import BoundedMail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_marshmallow import Marshmallow
from flask_talisman import Talisman

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = ApiCSRFProtect()
mail = BoundedMail()
limiter = Limiter(key_func=get_remote_address)
ma = Marshmallow()
talisman = Talisman()
