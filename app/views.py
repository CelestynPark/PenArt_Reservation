from __future__ import annotations
"""
SSR 화면 라우트
- 공개: / (랜딩), /artists, /gallery, /contact
- 로그인: /login
- 보호: /reservev(사용자), /admin(관리자)
서버단에서 토큰 검사 후 즉시 리다이렉스하여 '콘텐츠 깜빡임'을 방지
"""

from flask import Blueprint, render_template, redirect, request

bp = Blueprint("views", __name__)

@bp.get("/")
def home():
    # 공개 랜딩
    return render_template("index.html")

@bp.get("/artists")
def artists():
    return render_template("artists/index.html")

@bp.get("/gallery")
def gallery():
    return render_template("gallery/index.html")

@bp.get("/contact")
def contact():
    return render_template("contact/index.html")

@bp.get("/login")
def login_page():
    # 이미 로그인한 경우 역할에 따라 이동
    ident = None
    if ident:
        roles = ident.get("roles", [])
        return redirect("/admin" if "admin" in roles else "/reserve")
    return render_template("/login/index.html")

@bp.get("/reserve")
def reserve_page():
    # 로그인 필수
    ident = None
    if not ident:
        return redirect("/login")
    # 사용자 전용 UI
    return render_template("/reserve/index.html", me=ident)

@bp.get("/admin")
def admin_page():
    # 관리자만
    ident = None
    if not ident or "admin" not in ident.get("roles", []):
        # 미인증/권한 없음 -> 로그인으로 즉시 리다이렉트
        return redirect("/login")
    return render_template("admin/index.html", me=ident)

