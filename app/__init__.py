from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv
import os

from app.models import db, User  # ✅ Import shared db instance

login_manager = LoginManager()

def create_app():
    # ✅ Specify static folder path
    app = Flask(__name__, static_folder='static')
    load_dotenv()

    # ✅ Configurations
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ✅ Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "routes.admin_login"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ✅ Register blueprints
    from app.routes import routes
    app.register_blueprint(routes)

    return app

# ✅ Expose app instance for Gunicorn or Railway deployment
app = create_app()
