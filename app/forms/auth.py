from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email, Length, Regexp


class LoginForm(FlaskForm):
    email = StringField('Correo electrónico', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(max=128)])
    captcha = StringField('Número verificador', validators=[DataRequired(), Length(max=4)])


class TwoFactorForm(FlaskForm):
    code = StringField('Código de verificación', validators=[DataRequired(), Regexp(r'^\d{6}$', message='Ingresá los seis dígitos.')])
