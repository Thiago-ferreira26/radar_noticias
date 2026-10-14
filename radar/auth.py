"""Acesso de administrador do painel.

Usuário e senha ficam fora do código, em ADMIN_USER / ADMIN_PASSWORD (.env ou Secrets do
Streamlit Cloud). O login vale para a sessão do navegador; ao recarregar a página, entra de novo.
"""
from __future__ import annotations

import hmac
import time

import streamlit as st

from . import config

MAX_ATTEMPTS = 5
LOCK_SECONDS = 300


def _credentials() -> tuple[str, str] | None:
    user, password = config.secret("ADMIN_USER"), config.secret("ADMIN_PASSWORD")
    return (user, password) if user and password else None


def is_configured() -> bool:
    return _credentials() is not None


def is_admin() -> bool:
    return bool(st.session_state.get("is_admin"))


def _check(user: str, password: str) -> bool:
    creds = _credentials()
    if not creds:
        return False
    # compare_digest: tempo constante, não revela quantos caracteres estão certos
    ok_user = hmac.compare_digest(user.strip().encode(), creds[0].encode())
    ok_pass = hmac.compare_digest(password.encode(), creds[1].encode())
    return ok_user and ok_pass


def _locked_for() -> int:
    until = st.session_state.get("admin_locked_until", 0)
    return max(0, int(until - time.time()))


def login_widget() -> None:
    """Botão no topo da página: formulário de login ou, já logado, a opção de sair."""
    if is_admin():
        with st.popover("🔓 Administrador", width="stretch"):
            st.caption("Você está na visão de administrador.")
            if st.button("Sair", key="admin_logout", width="stretch"):
                st.session_state["is_admin"] = False
                st.rerun()
        return

    with st.popover("🔒 Área do administrador", width="stretch"):
        if not is_configured():
            st.warning("Acesso de administrador não configurado: defina ADMIN_USER e ADMIN_PASSWORD "
                       "no .env (ou em Secrets no Streamlit Cloud).")
            return
        if wait := _locked_for():
            st.error(f"Muitas tentativas erradas. Tente de novo em {wait // 60 + 1} min.")
            return
        with st.form("admin_login", clear_on_submit=True, border=False):
            user = st.text_input("Usuário", key="admin_user")
            password = st.text_input("Senha", type="password", key="admin_password")
            sent = st.form_submit_button("Entrar", type="primary", width="stretch")
        if sent:
            if _check(user, password):
                st.session_state.update(is_admin=True, admin_attempts=0)
                st.rerun()
            attempts = st.session_state.get("admin_attempts", 0) + 1
            st.session_state["admin_attempts"] = attempts
            time.sleep(1)  # atrasa tentativas automáticas
            if attempts >= MAX_ATTEMPTS:
                st.session_state.update(admin_locked_until=time.time() + LOCK_SECONDS, admin_attempts=0)
                st.error("Muitas tentativas erradas. Login bloqueado por 5 minutos.")
            else:
                st.error(f"Usuário ou senha inválidos ({attempts}/{MAX_ATTEMPTS}).")
