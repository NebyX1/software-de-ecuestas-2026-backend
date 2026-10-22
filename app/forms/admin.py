from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo


class AdminUserCreateForm(FlaskForm):
    username = StringField('Nombre de usuario', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Correo electrónico', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = PasswordField('Confirmar contraseña', validators=[DataRequired(), EqualTo('password')])
    is_superuser = BooleanField('Super administrador')


class AdminUserUpdateForm(FlaskForm):
    username = StringField('Nombre de usuario', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Correo electrónico', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Nueva contraseña', validators=[Optional(), Length(min=12, max=128)])
    confirm_password = PasswordField('Confirmar contraseña', validators=[EqualTo('password')])
    is_superuser = BooleanField('Super administrador')
    is_active = BooleanField('Usuario activo')
