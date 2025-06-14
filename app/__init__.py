from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from dotenv import load_dotenv
import os

from app.models import db, User  # Shared db instance and User model

login_manager = LoginManager()
migrate = Migrate()

def create_app():
    # Create Flask app
    app = Flask(__name__, static_folder='static')
    load_dotenv()

    # Configuration
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "defaultsecret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)  # 🔧 Migrate integration

    login_manager.login_view = "routes.admin_login"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register routes
    from app.routes import routes
    app.register_blueprint(routes)

    return app

# Expose app instance
app = create_app()
