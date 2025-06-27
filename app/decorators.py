from functools import wraps
from flask import session, redirect, url_for, flash
from flask_login import current_user

def user_or_subuser_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        # Main user (Flask-Login)
        if current_user.is_authenticated:
            return view_func(*args, **kwargs)
        # Subuser (session-based)
        elif session.get('subuser_id'):
            return view_func(*args, **kwargs)
        else:
            flash("Please log in to continue.", "danger")
            return redirect(url_for("routes.user_login"))
    return wrapper
