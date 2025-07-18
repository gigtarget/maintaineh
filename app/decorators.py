from functools import wraps
from flask import session, redirect, url_for, flash
from flask_login import current_user

def subuser_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print("\n======== DEBUG (subuser_required) ========")
        print("session:", dict(session))
        print("==========================================")
        if not session.get('subuser_id'):
            flash("Please log in as sub-user", "danger")
            return redirect(url_for("routes.subuser_login"))
        return f(*args, **kwargs)
    return decorated_function

def user_or_subuser_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        print("\n======== DEBUG (user_or_subuser_required) ========")
        print("current_user.is_authenticated:", current_user.is_authenticated)
        print("session:", dict(session))
        print("session.get('subuser_id'):", session.get('subuser_id'))
        print("==================================================")
        if current_user.is_authenticated:
            return view_func(*args, **kwargs)
        elif session.get('subuser_id'):
            return view_func(*args, **kwargs)
        else:
            flash("Please log in to continue.", "danger")
            return redirect(url_for("routes.user_login"))
    return wrapper
    
