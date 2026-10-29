"""Dados cadastrais da empresa pelo CNPJ (API pública OpenCNPJ), para completar o lead do Bitrix.

Aparece no botão "Enviar para o Bitrix" do card; os dados vão como texto no corpo do lead.
"""
from __future__ import annotations

import re
from html import escape

import requests

API_URL = "https://api.opencnpj.org/{}"
TIMEOUT = 10
MAX_SOCIOS = 5


def limpar_cnpj(cnpj: str) -> str:
    """Remove a pontuação do CNPJ e confere tamanho e dígitos verificadores (ValueError se inválido)."""
    limpo = re.sub(r"\D", "", str(cnpj or ""))
    if len(limpo) != 14 or len(set(limpo)) == 1:
        raise ValueError("CNPJ inválido: informe os 14 dígitos.")

    def digito(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    if limpo[12:] != digito(limpo[:12]) + digito(limpo[:13]):
        raise ValueError("CNPJ inválido: os dígitos verificadores não conferem.")
    return limpo


def formatar_cnpj(limpo: str) -> str:
    return f"{limpo[:2]}.{limpo[2:5]}.{limpo[5:8]}/{limpo[8:12]}-{limpo[12:]}"


def consultar(cnpj: str) -> dict:
    """Resposta completa da OpenCNPJ. LookupError se o CNPJ não existir; RequestException em falha de rede."""
    limpo = limpar_cnpj(cnpj)
    response = requests.get(API_URL.format(limpo), timeout=TIMEOUT)
    if response.status_code == 404:
        raise LookupError(f"CNPJ {formatar_cnpj(limpo)} não encontrado na Receita Federal.")
    response.raise_for_status()
    return response.json()


def _moeda(valor: str | None) -> str:
    try:
        n = float(str(valor).replace(".", "").replace(",", "."))
    except ValueError:
        return ""
    return "R$ " + f"{n:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _data(iso: str | None) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m[3]}/{m[2]}/{m[1]}" if m else ""


def resumo(dados: dict) -> dict:
    """Só o que interessa ao comercial, já formatado (rótulo → valor), mais a lista de sócios/diretores."""
    cnae = next((c for c in dados.get("cnaes") or [] if c.get("is_principal")), None)
    endereco = " ".join(filter(None, [dados.get("tipo_logradouro"), dados.get("logradouro")]))
    endereco = ", ".join(filter(None, [endereco, dados.get("numero"), " ".join((dados.get("complemento") or "").split()),
                                       dados.get("bairro")]))
    cep = dados.get("cep") or ""
    telefones = [f"({t['ddd']}) {t['numero'][:-4]}-{t['numero'][-4:]}" for t in dados.get("telefones") or []
                 if t.get("ddd") and len(t.get("numero") or "") >= 8 and not t.get("is_fax")]
    campos = {
        "CNPJ": formatar_cnpj(dados.get("cnpj") or ""),
        "Razão social": dados.get("razao_social"),
        "Nome fantasia": dados.get("nome_fantasia"),
        "Situação": " · ".join(filter(None, [dados.get("situacao_cadastral"), dados.get("matriz_filial")])),
        "Atividade principal": f"{cnae['descricao']} ({cnae['codigo']})" if cnae else dados.get("cnae_principal"),
        "Natureza jurídica": dados.get("natureza_juridica"),
        "Porte": dados.get("porte_empresa"),
        "Capital social": _moeda(dados.get("capital_social")),
        "Abertura": _data(dados.get("data_inicio_atividade")),
        "Endereço": endereco,
        "Cidade": " / ".join(filter(None, [(dados.get("municipio") or "").title(), dados.get("uf")]))
                  + (f" · CEP {cep[:5]}-{cep[5:]}" if len(cep) == 8 else ""),
        "Telefone": " · ".join(telefones),
        "E-mail": (dados.get("email") or "").lower(),
    }
    socios = [f"{s.get('nome_socio', '').title()} ({s.get('qualificacao_socio')})"
              for s in (dados.get("QSA") or [])[:MAX_SOCIOS] if s.get("nome_socio")]
    return {"campos": {k: v for k, v in campos.items() if v}, "socios": socios,
            "mais_socios": max(0, len(dados.get("QSA") or []) - MAX_SOCIOS)}


def bloco_lead(res: dict) -> str:
    """Trecho HTML para o corpo do lead (campo COMMENTS do Bitrix)."""
    linhas = "".join(f"<b>{escape(k)}:</b> {escape(str(v))}<br>" for k, v in res["campos"].items())
    if res["socios"]:
        extra = f" e mais {res['mais_socios']}" if res["mais_socios"] else ""
        linhas += f"<b>Sócios/diretores:</b> {escape('; '.join(res['socios']))}{extra}<br>"
    return "<br><br><b>Empresa (dados da Receita Federal via OpenCNPJ)</b><br>" + linhas
