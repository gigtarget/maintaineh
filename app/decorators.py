from functools import wraps
from flask import session, redirect, url_for, flash

def subuser_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('subuser_id'):
            flash("Please log in as sub-user", "danger")
            return redirect(url_for("routes.subuser_login"))
        return f(*args, **kwargs)
    return decorated_function
