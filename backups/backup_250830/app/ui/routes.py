from __future__ import annotations
from flask import Blueprint, render_template, redirect, url_for

bp = Blueprint('ui', __name__, template_folder='../templates')

@bp.get('/')
def home():
    return redirect(url_for('ui.schedule_page'))

@bp.get('/login')
def login():
    return render_template('auth/login.html')

@bp.get('/signup')
def signup():
    return render_template('auth/signup.html')

@bp.get('/schedule')
def schedule():
    return render_template('schedule/week.html')

