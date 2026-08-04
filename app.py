# -*- coding: utf-8 -*-
"""Ecossistema de RH Inovador v9.0 — gestao de usuarios, permissoes, edicao de candidatos, chat."""

import os
import re
import random
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'rh-inovador-2026')
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'ecossistema_rh.db'))
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins='*')

MAX_CONEXOES = 5
conexoes_ativas = 0

ETAPAS = ['triagem', 'entrevista', 'proposta', 'contratado', 'rejeitado']
ETAPAS_INFO = {
    'triagem': ('Triagem', '#3b82f6'),
    'entrevista': ('Entrevista', '#22d3ee'),
    'proposta': ('Proposta', '#f59e0b'),
    'contratado': ('Contratado', '#10b981'),
    'rejeitado': ('Rejeitado', '#ef4444'),
}

GRUPOS = ['candidato', 'empresa', 'analista', 'gerencia', 'diretor']
GRUPO_LABEL = {
    'candidato': '👤 Candidato',
    'empresa': '🏢 Empresa',
    'analista': '🧑‍💼 Analista',
    'gerencia': '📊 Gerência',
    'diretor': '👑 Diretor',
}
MODULOS_GERENCIAVEIS = ['vagas', 'candidatos', 'empresas', 'pcs', 'analytics', 'mensagens',
                        'pipeline', 'entrevistas', 'testes', 'etapas', 'monitoramento', 'financeiro',
                        'cadastrar_vaga', 'cadastrar_empresa', 'importar_plano', 'perfil', 'painel']
PERMISSOES_PADRAO = {
    'candidato': ['vagas', 'candidatos', 'pcs', 'analytics', 'mensagens', 'perfil', 'painel'],
    'empresa': ['vagas', 'candidatos', 'empresas', 'pcs', 'analytics', 'mensagens',
                'pipeline', 'entrevistas', 'testes', 'etapas', 'monitoramento',
                'cadastrar_vaga', 'cadastrar_empresa', 'importar_plano', 'perfil', 'painel'],
    'analista': ['vagas', 'candidatos', 'empresas', 'pcs', 'analytics', 'mensagens',
                 'pipeline', 'entrevistas', 'testes', 'etapas', 'monitoramento', 'financeiro',
                 'cadastrar_vaga', 'perfil', 'painel'],
    'gerencia': ['vagas', 'candidatos', 'empresas', 'pcs', 'analytics', 'mensagens',
                 'pipeline', 'entrevistas', 'testes', 'etapas', 'monitoramento', 'financeiro',
                 'cadastrar_vaga', 'cadastrar_empresa', 'importar_plano', 'perfil', 'painel'],
    'diretor': MODULOS_GERENCIAVEIS,
}
PERMISSOES_PADRAO = {
    'candidato': ['vagas', 'candidatos', 'pcs', 'analytics', 'mensagens', 'perfil', 'painel'],
    'empresa': MODULOS_GERENCIAVEIS,
}

# ================= MODELOS =================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    ativo = db.Column(db.Boolean, default=True)

class Perfil(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), unique=True)
    skills = db.Column(db.Text)
    resumo = db.Column(db.Text)
    linkedin = db.Column(db.String(200))

class Permissao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    modulo = db.Column(db.String(50), nullable=False)
    habilitado = db.Column(db.Boolean, default=True)

class GrupoPermissao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grupo = db.Column(db.String(30), nullable=False)
    modulo = db.Column(db.String(50), nullable=False)
    habilitado = db.Column(db.Boolean, default=True)

def tem_permissao(u, modulo):
    if not u:
        return False
    if u.tipo == 'admin':
        return True
    if modulo not in MODULOS_GERENCIAVEIS:
        return True
    grupo = (u.grupo or u.tipo or 'candidato')
    if grupo == 'admin':
        return True
    gp = GrupoPermissao.query.filter_by(grupo=grupo, modulo=modulo).first()
    if gp:
        return gp.habilitado
    return modulo in PERMISSOES_PADRAO.get(grupo, [])

def grupo_do_usuario(u):
    return (u.grupo or u.tipo or 'candidato')

def garantir_permissoes():
    for g in GRUPOS:
        for mod in MODULOS_GERENCIAVEIS:
            if not GrupoPermissao.query.filter_by(grupo=g, modulo=mod).first():
                db.session.add(GrupoPermissao(grupo=g, modulo=mod,
                                              habilitado=mod in PERMISSOES_PADRAO.get(g, [])))
    for u in Usuario.query.filter(Usuario.tipo != 'admin').all():
        if not u.grupo:
            u.grupo = u.tipo
    db.session.commit()

def contar_nao_lidas(u):
    convs = Conversa.query.filter((Conversa.candidato_id == u.id) | (Conversa.empresa_id == u.id)).all()
    total = 0
    for c in convs:
        total += Mensagem.query.filter_by(conversa_id=c.id, lida=False).filter(Mensagem.remetente_id != u.id).count()
    return total

# ================= SEED =================
def criar_dados_iniciais():
    if Usuario.query.first():
        return
    admin = Usuario(nome='Administrador', email='admin@rh.com',
                    senha_hash=generate_password_hash('admin123'), tipo='admin', ativo=True)
    cand = Usuario(nome='Maria Silva', email='candidato@teste.com',
                   senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True)
    cand2 = Usuario(nome='João Pereira', email='joao@teste.com',
                    senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True)
    cand3 = Usuario(nome='Ana Souza', email='ana@teste.com',
                    senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True)
    emp = Usuario(nome='RH Inovador S.A.', email='empresa@teste.com',
                  senha_hash=generate_password_hash('empresa123'), tipo='empresa', ativo=True)
    db.session.add_all([admin, cand, cand2, cand3, emp])
    db.session.flush()
    db.session.add(Empresa(usuario_id=emp.id, razao_social='RH Inovador S.A.',
                           nome_fantasia='RH Inovador', cnpj='00.000.000/0001-00',
                           porte='Pequeno', setor='Tecnologia',
                           descricao='Plataforma de talentos.', cultura='Inovacao e gente'))
    t1 = Trilha(nome='Carreira Técnica', descricao='Especialização técnica em tecnologia')
    t2 = Trilha(nome='Carreira de Gestão', descricao='Liderança e gestão de pessoas')
    t3 = Trilha(nome='Carreira Comercial', descricao='Vendas e relacionamento com clientes')
    db.session.add_all([t1, t2, t3])
    db.session.flush()
    niveis = [
        (t1.id, 'EST', 'Estagiário', 1, 1200, 2500, 'Supervisionada', 'Individual'),
        (t1.id, 'JR1', 'Júnior I', 2, 2500, 4000, 'Assistida', 'Individual'),
        (t1.id, 'JR2', 'Júnior II', 3, 3500, 5500, 'Guiada', 'Individual'),
        (t1.id, 'JR3', 'Júnior III', 4, 4500, 7000, 'Moderada', 'Individual'),
        (t1.id, 'PL1', 'Pleno I', 5, 6000, 9000, 'Independente', 'Time'),
        (t1.id, 'PL2', 'Pleno II', 6, 8000, 12000, 'Independente', 'Time'),
        (t1.id, 'PL3', 'Pleno III', 7, 10000, 15000, 'Autônoma', 'Time'),
        (t1.id, 'SR1', 'Sênior I', 8, 13000, 18000, 'Autônoma', 'Área'),
        (t1.id, 'SR2', 'Sênior II', 9, 16000, 22000, 'Proativa', 'Área'),
        (t1.id, 'SR3', 'Sênior III', 10, 19000, 26000, 'Direcionadora', 'Organização'),
        (t1.id, 'MS1', 'Master I', 11, 23000, 32000, 'Visionária', 'Mercado'),
        (t1.id, 'MS2', 'Master II', 12, 28000, 40000, 'Visionária', 'Indústria'),
        (t1.id, 'FEL', 'Fellow', 13, 35000, 50000, 'Autoridade', 'Sociedade'),
        (t2.id, 'GJR', 'Gestão Júnior', 1, 5000, 8000, 'Guiada', 'Time'),
        (t2.id, 'GPL', 'Gestão Pleno', 2, 8000, 14000, 'Independente', 'Área'),
        (t2.id, 'GSR', 'Gestão Sênior', 3, 15000, 25000, 'Estratégica', 'Organização'),
        (t2.id, 'GDIR', 'Diretoria', 4, 25000, 50000, 'Visionária', 'Mercado'),
        (t3.id, 'CJR', 'Comercial Júnior', 1, 2500, 4500, 'Assistida', 'Individual'),
        (t3.id, 'CPL', 'Comercial Pleno', 2, 4500, 8000, 'Independente', 'Time'),
        (t3.id, 'CSR', 'Comercial Sênior', 3, 8000, 15000, 'Autônoma', 'Área'),
        (t3.id, 'CGR', 'Gerência Comercial', 4, 15000, 30000, 'Visionária', 'Organização'),
    ]
    for tr, cod, nome, ordn, smin, smax, aut, imp in niveis:
        db.session.add(Nivel(trilha_id=tr, codigo=cod, nome=nome, ordem=ordn,
                             salario_min=smin, salario_max=smax, autonomia=aut, impacto=imp))
    db.session.add_all([
        Vaga(titulo='Desenvolvedor(a) Python Pleno', descricao='Flask, SQL e APIs REST. 100% remoto.',
             empresa='RH Inovador S.A.', nivel_codigo='PL2', regime='Remoto', localizacao='Brasil'),
        Vaga(titulo='Analista de Gente e Gestão', descricao='Suporte ao PCS, carreiras e promoções.',
             empresa='RH Inovador S.A.', nivel_codigo='GPL', regime='Híbrido', localizacao='Curitiba/PR'),
        Vaga(titulo='Engenheiro(a) de IA Sênior', descricao='Matching preditivo e agentes autônomos.',
             empresa='Tech Solutions', nivel_codigo='SR2', regime='Remoto', localizacao='Brasil'),
        Vaga(titulo='Executivo(a) de Contas', descricao='Gestão de carteira de clientes corporativos.',
             empresa='Tech Solutions', nivel_codigo='CPL', regime='Híbrido', localizacao='São Paulo/SP'),
        Vaga(titulo='Estagiário(a) de RH', descricao='Apoio ao time de gente e gestão.',
             empresa='RH Inovador S.A.', nivel_codigo='EST', regime='Presencial', localizacao='Curitiba/PR'),
    ])
    db.session.commit()

def garantir_dados_demo():
    """Cria perfis, skills e requisitos de exemplo (idempotente — nao apaga nada)."""
    skills_demo = {
        'candidato@teste.com': 'python, flask, sql, api rest, comunicação',
        'joao@teste.com': 'javascript, react, node, ui, comunicação',
        'ana@teste.com': 'marketing, vendas, excel, comunicação, negociação',
    }
    for email, sk in skills_demo.items():
        u = Usuario.query.filter_by(email=email).first()
        if u and not Perfil.query.filter_by(usuario_id=u.id).first():
            db.session.add(Perfil(usuario_id=u.id, skills=sk,
                                  resumo='Profissional em busca de novos desafios.'))
    reqs_demo = {
        'Desenvolvedor(a) Python Pleno': ['python', 'flask', 'sql', 'api rest'],
        'Analista de Gente e Gestão': ['rh', 'carreiras', 'excel', 'comunicação'],
        'Engenheiro(a) de IA Sênior': ['python', 'machine learning', 'llm', 'dados'],
        'Executivo(a) de Contas': ['vendas', 'negociação', 'excel', 'comunicação'],
        'Estagiário(a) de RH': ['organização', 'comunicação', 'excel', 'proatividade'],
    }
    for titulo, reqs in reqs_demo.items():
        v = Vaga.query.filter_by(titulo=titulo).first()
        if v and not Requisito.query.filter_by(vaga_id=v.id).first():
            for r in reqs:
                db.session.add(Requisito(vaga_id=v.id, skill=r))
    db.session.commit()

def garantir_permissoes():
    for u in Usuario.query.filter(Usuario.tipo != 'admin').all():
        for mod in MODULOS_GERENCIAVEIS:
            if not Permissao.query.filter_by(usuario_id=u.id, modulo=mod).first():
                db.session.add(Permissao(usuario_id=u.id, modulo=mod,
                                         habilitado=mod in PERMISSOES_PADRAO.get(u.tipo, [])))
    db.session.commit()

# ================= WEBSOCKET =================
@socketio.on('connect')
def on_connect():
    global conexoes_ativas
    if conexoes_ativas >= MAX_CONEXOES:
        return False
    conexoes_ativas += 1
    emit('status', {'conexoes': conexoes_ativas, 'max': MAX_CONEXOES}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    global conexoes_ativas
    if conexoes_ativas > 0:
        conexoes_ativas -= 1
    emit('status', {'conexoes': conexoes_ativas, 'max': MAX_CONEXOES}, broadcast=True)

@socketio.on('entrar_sala')
def on_entrar_sala(data):
    cid = data.get('conversa_id')
    if cid:
        join_room(str(cid))

@socketio.on('sair_sala')
def on_sair_sala(data):
    cid = data.get('conversa_id')
    if cid:
        leave_room(str(cid))

# ================= AUTENTICACAO =================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = usuario_atual()
        if not u or u.tipo != 'admin':
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper

def gestor_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = usuario_atual()
        if not u or u.tipo not in ('admin', 'empresa'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper

def usuario_atual():
    uid = session.get('user_id')
    if uid:
        return Usuario.query.get(uid)
    return None

# ================= LAYOUT =================
def pagina(conteudo, ativo=''):
    u = usuario_atual()
    nav = [
        ('/', '🏠', 'Dashboard'),
        ('/recrutamento', '🧠', 'Recrutamento Inteligente'),
        ('/candidatos', '👤', 'Candidatos'),
        ('/empresas', '🏢', 'Empresas'),
        ('/pcs', '📊', 'Plano de Cargos e Salários'),
        ('/conectividade', '📡', 'Conectividade'),
        ('/vagas', '💼', 'Vagas'),
        ('/analytics', '📈', 'Analytics'),
        ('/experiencia', '🎯', 'Experiência'),
        ('/inovacao', '🚀', 'Inovação'),
    ]
    if u:
        nao_lidas = contar_nao_lidas(u)
        badge = (' <span class="pill nv">' + str(nao_lidas) + '</span>') if nao_lidas else ''
        if tem_permissao(u, 'mensagens'):
            nav.append(('/mensagens', '💬', 'Mensagens'))
        if tem_permissao(u, 'perfil'):
            nav.append(('/perfil', '👤', 'Meu Perfil'))
        if tem_permissao(u, 'importar_plano'):
            nav.append(('/importar-plano', '📥', 'Importar Plano'))
        if u.tipo in ('admin', 'empresa'):
            if tem_permissao(u, 'pipeline'):
                nav.append(('/pipeline', '📋', 'Pipeline'))
            if tem_permissao(u, 'entrevistas'):
                nav.append(('/entrevistas', '🎥', 'Entrevistas'))
            if u.tipo == 'admin':
                nav.append(('/cadastrar-candidato', '👤➕', 'Cadastrar Candidato'))
                nav.append(('/gerenciar', '⚙️', 'Gerenciar'))
        else:
            nav.append(('/minhas-entrevistas', '🎥', 'Entrevistas'))
        if tem_permissao(u, 'painel'):
                    if u.tipo in ('admin', 'empresa'):
            nav.append(('/config-etapas', '🧪', 'Etapas e Testes'))
            nav.append(('/monitoramento', '📊', 'Monitoramento'))
            nav.append(('/financeiro', '💰', 'Financeiro'))
            nav.append(('/painel', '🔑', 'Meu Painel'))
    itens = ''
    for href, icone, nome in nav:
        cls = ' class="ativo"' if href == ativo else ''
        if 'Mensagens' in nome and badge:
            itens += '<a href="' + href + '"' + cls + '>' + icone + ' ' + nome + badge + '</a>'
        else:
            itens += '<a href="' + href + '"' + cls + '>' + icone + ' ' + nome + '</a>'
    if u:
        chip = ('<div class="chip"><span class="pill ' + u.tipo + '">' + u.tipo + '</span> '
                '<b>' + u.nome + '</b> '
                '<a class="link" href="/perfil">Perfil</a> | '
                '<a class="link" href="/logout">Sair</a></div>')
    else:
        chip = ('<div class="chip"><a class="btn" href="/login">🔑 Entrar</a> '
                '<a class="btn cinza" href="/registro">📝 Criar conta</a></div>')
    base = '''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ecossistema RH Inovador</title><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
body{background:radial-gradient(1200px 600px at 80% -10%,rgba(34,211,238,.08),transparent),radial-gradient(900px 500px at 10% 110%,rgba(168,85,247,.08),transparent),#0a1628;color:#e5eaf3;display:flex;min-height:100vh}
aside{width:240px;background:rgba(13,27,48,.85);backdrop-filter:blur(12px);border-right:1px solid rgba(28,47,74,.7);padding:20px 14px;flex-shrink:0}
aside h2{font-size:14px;color:#22d3ee;margin-bottom:20px;letter-spacing:.5px;text-shadow:0 0 12px rgba(34,211,238,.5)}
aside nav a{display:block;padding:9px 12px;border-radius:8px;color:#9fb0c8;text-decoration:none;font-size:13px;margin-bottom:3px;transition:.2s}
aside nav a:hover{background:rgba(22,40,63,.8);color:#fff}
aside nav a.ativo{background:linear-gradient(90deg,#1d4ed8,#0ea5e9);color:#fff;box-shadow:0 4px 16px rgba(29,78,216,.4)}
main{flex:1;padding:26px 32px;overflow-y:auto}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}
header h1{font-size:22px}header h1 span{color:#22d3ee}
.chip{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px}
.btn{background:linear-gradient(90deg,#1d4ed8,#0ea5e9);color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;font-size:13px;border:none;cursor:pointer;box-shadow:0 4px 14px rgba(29,78,216,.35)}
.btn.cinza{background:rgba(30,41,59,.8)}.btn:hover{opacity:.92}
.btn.verde{background:linear-gradient(90deg,#059669,#10b981)}
.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-bottom:24px}
.card{background:rgba(15,33,64,.5);backdrop-filter:blur(14px);border:1px solid rgba(59,130,246,.22);border-radius:14px;padding:20px;transition:.25s}
.card:hover{border-color:rgba(34,211,238,.6);transform:translateY(-3px);box-shadow:0 8px 30px rgba(34,211,238,.15)}
.card .icone{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;margin-bottom:12px}
.card h3{font-size:15px;margin-bottom:6px}.card p{font-size:12px;color:#8fa3c0;line-height:1.5}
.painel{background:rgba(13,27,48,.6);backdrop-filter:blur(10px);border:1px solid rgba(28,47,74,.6);border-radius:14px;padding:20px 24px;margin-bottom:20px}
.painel h4{font-size:12px;color:#8fa3c0;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}
.status{display:flex;flex-wrap:wrap;gap:18px;font-size:14px}
.item{display:flex;align-items:center;gap:9px}
.dot{width:10px;height:10px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981}
.dot.roxo{background:#a855f7;box-shadow:0 0 8px #a855f7}
.dot.ciano{background:#22d3ee;box-shadow:0 0 8px #22d3ee}
.tabela{width:100%;border-collapse:collapse;font-size:13px}
.tabela th{text-align:left;color:#8fa3c0;padding:10px;border-bottom:1px solid rgba(28,47,74,.8);text-transform:uppercase;font-size:11px;letter-spacing:.5px}
.tabela td{padding:10px;border-bottom:1px solid rgba(22,40,63,.8)}
.tabela tr:hover td{background:rgba(15,33,64,.6)}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px}
.pill.aberta,.pill.candidato,.pill.contratado,.pill.realizada{background:rgba(16,185,129,.14);color:#10b981}
.pill.fechada,.pill.rejeitado,.pill.cancelada{background:rgba(239,68,68,.14);color:#ef4444}
.pill.empresa{background:rgba(245,158,11,.14);color:#f59e0b}
.pill.admin{background:rgba(168,85,247,.14);color:#a855f7}
.pill.pendente,.pill.triagem,.pill.proposta,.pill.agendada{background:rgba(245,158,11,.14);color:#f59e0b}
.pill.entrevista,.pill.confirmada{background:rgba(34,211,238,.14);color:#22d3ee}
.pill.nv{background:rgba(239,68,68,.2);color:#f87171}
form label{display:block;margin:12px 0 5px;font-size:13px;color:#9fb0c8}
form input,form select,form textarea{width:100%;background:rgba(10,22,40,.8);border:1px solid rgba(28,47,74,.8);border-radius:8px;padding:10px 12px;color:#fff;font-size:14px}
form input:focus,form select:focus,form textarea:focus{outline:none;border-color:#22d3ee}
.mensagem{display:none;margin-top:14px;padding:12px;border-radius:8px;font-size:13px}
.mensagem.ok{display:block;background:rgba(16,185,129,.14);color:#10b981}
.mensagem.erro{display:block;background:rgba(239,68,68,.14);color:#ef4444}
.link{color:#22d3ee;text-decoration:none}
.sub{color:#8fa3c0;font-size:13px;margin-bottom:18px}
.caixa-busca{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.caixa-busca input,.caixa-busca select{width:auto;min-width:160px}
.medalha{display:inline-block;min-width:30px;text-align:center;font-weight:700}
.kanban{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px}
.kcol{background:rgba(10,22,40,.5);border:1px solid rgba(28,47,74,.6);border-radius:12px;padding:12px;min-height:220px}
.kcol h4{font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;color:#8fa3c0;display:flex;justify-content:space-between;align-items:center}
.kcard{background:rgba(15,33,64,.75);border:1px solid rgba(59,130,246,.25);border-radius:10px;padding:10px;margin-bottom:10px;transition:.2s}
.kcard:hover{border-color:rgba(34,211,238,.5)}
.kcard b{font-size:13px;display:block}
.kcard .meta{font-size:11px;color:#8fa3c0;margin-top:4px}
.kbtns{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.kbtn{background:rgba(30,41,59,.9);color:#fff;border:1px solid rgba(59,130,246,.35);border-radius:6px;padding:4px 9px;font-size:11px;cursor:pointer;text-decoration:none;display:inline-block}
.kbtn:hover{background:#1d4ed8}
.kbtn.verde:hover{background:#059669}
.kbtn.roxo:hover{background:#7c3aed}
.chatbox{max-height:380px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding:6px 2px}
.bubble{max-width:75%;padding:10px 14px;border-radius:14px;font-size:13px;line-height:1.45}
.bubble.minha{align-self:flex-end;background:linear-gradient(90deg,#1d4ed8,#0ea5e9);border-bottom-right-radius:4px}
.bubble.dela{align-self:flex-start;background:rgba(30,41,59,.9);border:1px solid rgba(28,47,74,.8);border-bottom-left-radius:4px}
.bubble .hora{display:block;font-size:10px;opacity:.7;margin-top:4px}
.chatbar{display:flex;gap:10px;margin-top:14px}
.chatbar input{flex:1}
.conv{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border:1px solid rgba(28,47,74,.6);border-radius:12px;margin-bottom:10px;background:rgba(15,33,64,.4);transition:.2s}
.conv:hover{border-color:rgba(34,211,238,.5)}
footer{margin-top:24px;color:#475569;font-size:12px}
@media(max-width:800px){body{flex-direction:column}aside{width:100%;border-right:none;border-bottom:1px solid rgba(28,47,74,.7)}main{padding:18px}}
</style></head><body>
<aside><h2>⚡ ECOSSISTEMA RH</h2><nav>@NAV@</nav></aside>
<main><header><h1>Ecossistema RH <span>// Inovador</span></h1>@CHIP@</header>
@CONTEUDO@
<footer>Ecossistema de RH Inovador v9.0 — dados permanentes | conexões em tempo real: <span id="conn">0/@MAX@</span></footer>
</main>
<script>
function conectarWs(){var ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host);
ws.onmessage=function(e){try{var d=JSON.parse(e.data);if(d.conexoes!==undefined)document.getElementById('conn').textContent=d.conexoes+'/'+d.max;}catch(_){}};
ws.onclose=function(){setTimeout(conectarWs,3000);};}conectarWs();
</script></body></html>'''
    return (base.replace('@NAV@', itens)
                .replace('@CHIP@', chip)
                .replace('@CONTEUDO@', conteudo)
                .replace('@MAX@', str(MAX_CONEXOES)))

# ================= AUTH (PAGINAS) =================
@app.route('/registro')
def registro():
    h = '<h1>Criar Conta <span>// Comece agora</span></h1><div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Nome completo</label><input id="nome" required placeholder="Seu nome">'
    h += '<label>E-mail</label><input id="email" type="email" required placeholder="voce@email.com">'
    h += '<label>Senha</label><input id="senha" type="password" required placeholder="Mínimo 6 caracteres">'
    h += '<label>Tipo de conta</label><select id="tipo"><option value="candidato">Candidato(a) — procuro emprego</option><option value="empresa">Empresa — quero contratar</option></select>'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Criar conta</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/registro",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({nome:document.getElementById("nome").value,email:document.getElementById("email").value,'
          'senha:document.getElementById("senha").value,tipo:document.getElementById("tipo").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Conta criada! Redirecionando...";setTimeout(function(){location.href="/painel";},800);}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/painel')

@app.route('/login')
def login():
    h = '<h1>Entrar <span>// Acesse seu painel</span></h1><div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>E-mail</label><input id="email" type="email" required placeholder="voce@email.com">'
    h += '<label>Senha</label><input id="senha" type="password" required placeholder="Sua senha">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Entrar</button></div>'
    h += '<div class="mensagem" id="msg"></div><p style="margin-top:14px;font-size:13px;color:#8fa3c0">'
    h += 'Teste: candidato@teste.com / candidato123 • empresa@teste.com / empresa123 • admin@rh.com / admin123</p>'
    h += '</form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({email:document.getElementById("email").value,senha:document.getElementById("senha").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Bem-vindo(a)! Redirecionando...";setTimeout(function(){location.href="/painel";},600);}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/painel')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('menu'))

# ================= MEU PERFIL =================
@app.route('/perfil')
@login_required
def perfil():
    u = usuario_atual()
    if not tem_permissao(u, 'perfil'):
        return redirect(url_for('painel'))
    p = Perfil.query.filter_by(usuario_id=u.id).first()
    sk = p.skills if p else ''
    resumo = p.resumo if p else ''
    link = p.linkedin if p else ''
    h = '<h1>Meu Perfil <span>// ' + u.nome + '</span></h1><p class="sub">Cadastre suas skills para o Match Score ficar mais preciso.</p>'
    h += '<div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Skills (separadas por vírgula)</label><textarea id="skills" rows="3" placeholder="ex: python, flask, sql, comunicação">' + sk + '</textarea>'
    h += '<label>Resumo profissional</label><textarea id="resumo" rows="3" placeholder="Conte um pouco sobre você">' + resumo + '</textarea>'
    h += '<label>LinkedIn (opcional)</label><input id="linkedin" value="' + link + '" placeholder="https://linkedin.com/in/...">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Salvar perfil</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/perfil",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({skills:document.getElementById("skills").value,resumo:document.getElementById("resumo").value,'
          'linkedin:document.getElementById("linkedin").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Perfil salvo!";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/perfil')

# ================= IMPORTAR PLANO =================
@app.route('/importar-plano')
@login_required
def importar_plano():
    u = usuario_atual()
    if not tem_permissao(u, 'importar_plano'):
        return redirect(url_for('painel'))
    h = '<h1>Importar Plano de Carreiras <span>// PCS</span></h1>'
    h += '<p class="sub">Cole a tabela do seu plano (Word/PDF). Cada linha = um nível. Formato: Trilha; Código; Nível; Sal. Mín; Sal. Máx; Autonomia; Impacto</p>'
    h += '<div class="painel" style="max-width:760px">'
    h += '<button class="btn cinza" type="button" onclick="preencherExemplo()" style="margin-bottom:10px">📋 Ver exemplo pronto</button>'
    h += '<label>Cole aqui as linhas do plano (uma por linha):</label>'
    h += '<textarea id="texto" rows="12" style="font-family:monospace" placeholder="Carreira Técnica; JR1; Júnior I; 2500; 4000; Assistida; Individual&#10;Carreira Técnica; JR2; Júnior II; 3500; 5500; Guiada; Individual"></textarea>'
    h += '<div style="margin-top:14px"><button class="btn verde" type="button" onclick="importar()">📥 Importar agora</button></div>'
    h += '<div class="mensagem" id="msg"></div></div>'
    h += ('<script>'
          'function preencherExemplo(){document.getElementById("texto").value='
          '"Carreira Técnica; JR1; Júnior I; 2500; 4000; Assistida; Individual\\n"'
          '+"Carreira Técnica; JR2; Júnior II; 3500; 5500; Guiada; Individual\\n"'
          '+"Carreira Técnica; PL1; Pleno I; 6000; 9000; Independente; Time\\n"'
          '+"Carreira de Gestão; GPL; Gestão Pleno; 8000; 14000; Independente; Área\\n"'
          '+"Carreira Comercial; CPL; Comercial Pleno; 4500; 8000; Independente; Time";}'
          'function importar(){var t=document.getElementById("texto").value;if(!t.trim()){return;}'
          'fetch("/api/importar-plano",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({texto:t})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){'
          'm.className="mensagem ok";m.innerHTML="✅ "+res.j.msg+" <a class=link href=/pcs>Ver PCS atualizado →</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/importar-plano')

# ================= ADMIN: CADASTRAR CANDIDATO =================
@app.route('/cadastrar-candidato')
@admin_required
def pagina_cadastrar_candidato():
    h = '<h1>Cadastrar Candidato <span>// Administração</span></h1>'
    h += '<p class="sub">Crie a conta de um candidato manualmente. Ele poderá entrar no sistema com o e-mail e a senha definidos aqui.</p>'
    h += '<div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Nome completo *</label><input id="nome" required placeholder="Nome do candidato">'
    h += '<label>E-mail *</label><input id="email" type="email" required placeholder="candidato@email.com">'
    h += '<label>Senha *</label><input id="senha" type="password" required placeholder="Mínimo 6 caracteres">'
    h += '<label>Skills (separadas por vírgula)</label><input id="skills" placeholder="ex: python, excel, comunicação">'
    h += '<label>Resumo profissional</label><textarea id="resumo" rows="3" placeholder="Breve resumo"></textarea>'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Cadastrar candidato</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/admin/cadastrar-candidato",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({nome:document.getElementById("nome").value,email:document.getElementById("email").value,'
          'senha:document.getElementById("senha").value,skills:document.getElementById("skills").value,'
          'resumo:document.getElementById("resumo").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Candidato cadastrado! <a class=link href=/candidatos>Ver candidatos</a>";'
          'document.getElementById("f").reset();}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/candidatos')

# ================= ADMIN: EDITAR CANDIDATO =================
@app.route('/editar-candidato/<int:uid>')
@admin_required
def editar_candidato(uid):
    alvo = Usuario.query.get(uid)
    if not alvo or alvo.tipo != 'candidato':
        return pagina('<h1>Candidato não encontrado</h1>', '/candidatos')
    p = Perfil.query.filter_by(usuario_id=uid).first()
    vagas = Vaga.query.order_by(Vaga.id.desc()).all()
    h = '<h1>✏️ Editar Candidato <span>// ' + alvo.nome + '</span></h1>'
    h += '<p class="sub"><a class="link" href="/candidatos">← Voltar para candidatos</a> • <a class="link" href="/gerenciar">⚙️ Gerenciar</a></p>'
    h += '<div class="painel" style="max-width:640px"><h4>📋 Dados do Candidato</h4><form id="f">'
    h += '<label>Nome *</label><input id="nome" required value="' + alvo.nome + '">'
    h += '<label>E-mail *</label><input id="email" type="email" required value="' + alvo.email + '">'
    h += '<label>Nova senha (deixe vazio para manter)</label><input id="senha" type="password" placeholder="Somente se quiser trocar">'
    h += '<label>Skills (separadas por vírgula)</label><input id="skills" value="' + (p.skills if p and p.skills else '') + '">'
    h += '<label>Resumo profissional</label><textarea id="resumo" rows="3">' + (p.resumo if p and p.resumo else '') + '</textarea>'
    h += '<label><input type="checkbox" id="ativo" ' + ('checked' if alvo.ativo else '') + ' style="width:auto"> Conta ativa (pode entrar)</label>'
    h += '<div style="margin-top:16px"><button class="btn verde" type="submit">💾 Salvar alterações</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += '<div class="painel" style="max-width:640px"><h4>🎥 Agendar Entrevista</h4><form id="f2">'
    h += '<label>Vaga *</label><select id="vaga_id" required><option value="">Selecione...</option>'
    for v in vagas:
        h += '<option value="' + str(v.id) + '">' + v.titulo + ' (' + (v.empresa or '') + ')</option>'
    h += '</select>'
    h += '<label>Data *</label><input id="data" type="date" required value="' + (datetime.utcnow() + timedelta(days=2)).strftime('%Y-%m-%d') + '">'
    h += '<label>Hora *</label><input id="hora" type="time" required value="14:00">'
    h += '<label>Tipo</label><select id="tipo"><option value="Video">🎥 Vídeo</option><option value="Presencial">🏢 Presencial</option><option value="Telefonica">📞 Telefônica</option></select>'
    h += '<label>Link da sala (opcional)</label><input id="link" placeholder="https://meet.google.com/...">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">🎥 Agendar entrevista</button></div>'
    h += '<div class="mensagem" id="msg2"></div></form></div>'
    convs = Conversa.query.filter_by(candidato_id=uid).all()
    if convs:
        h += '<div class="painel"><h4>💬 Conversas deste candidato</h4>'
        for c in convs:
            v = Vaga.query.get(c.vaga_id)
            h += '<p><a class="link" href="/mensagens/' + str(c.id) + '">💬 ' + (v.titulo if v else 'Vaga') + ' → abrir chat</a></p>'
        h += '</div>'
    ents = Entrevista.query.filter_by(candidato_id=uid).order_by(Entrevista.id.desc()).all()
    if ents:
        h += '<div class="painel"><h4>🎥 Entrevistas deste candidato</h4>'
        for e in ents:
            v = Vaga.query.get(e.vaga_id)
            nota = (' • ⭐ ' + str(int(e.nota)) + '/10') if e.nota is not None else ''
            h += '<p>📅 ' + e.data_hora.strftime('%d/%m/%Y %H:%M') + ' • ' + (v.titulo if v else '') + ' • <span class="pill ' + e.status + '">' + e.status + '</span>' + nota + '</p>'
        h += '</div>'
    h += ('<script>'
          'document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/admin/editar-candidato",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({usuario_id:' + str(uid) + ',nome:document.getElementById("nome").value,'
          'email:document.getElementById("email").value,senha:document.getElementById("senha").value,'
          'skills:document.getElementById("skills").value,resumo:document.getElementById("resumo").value,'
          'ativo:document.getElementById("ativo").checked})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Candidato atualizado!";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};'
          'document.getElementById("f2").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/admin/agendar-entrevista",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({candidato_id:' + str(uid) + ',vaga_id:document.getElementById("vaga_id").value,'
          'data:document.getElementById("data").value,hora:document.getElementById("hora").value,'
          'tipo:document.getElementById("tipo").value,link:document.getElementById("link").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg2");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Entrevista agendada! <a class=link href=/editar-candidato/' + str(uid) + '>Atualizar →</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/editar-candidato')

# ================= ADMIN: GERENCIAR PERMISSOES =================
@app.route('/gerenciar')
@admin_required
def gerenciar():
    h = '<h1>⚙️ Gerenciamento <span>// Grupos e Usuários</span></h1>'
    h += '<p class="sub">Configure as permissões por grupo (ON/OFF) e atribua cada usuário a um grupo.</p>'
    h += '<div class="painel"><h4>👥 GRUPOS — permissões ON/OFF</h4>'
    for g in GRUPOS:
        perms = {p.modulo: p.habilitado for p in GrupoPermissao.query.filter_by(grupo=g).all()}
        h += '<div style="border:1px solid rgba(28,47,74,.6);border-radius:12px;padding:14px;margin-bottom:12px">'
        h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        h += '<b>' + GRUPO_LABEL.get(g, g) + '</b>'
        h += '<button class="btn verde" onclick="salvarGrupo(\'' + g + '\')">💾 Salvar ' + g + '</button></div>'
        h += '<div class="status" id="mods_g_' + g + '">'
        for mod in MODULOS_GERENCIAVEIS:
            checked = ' checked' if perms.get(mod, mod in PERMISSOES_PADRAO.get(g, [])) else ''
            h += ('<label style="font-size:12px;display:flex;align-items:center;gap:4px;background:rgba(15,33,64,.5);'
                  'padding:4px 8px;border-radius:6px"><input type="checkbox" data-mod="' + mod + '"' + checked + ' style="width:auto"> '
                  + mod.replace('_', ' ').title() + '</label>')
        h += '</div><div class="mensagem" id="msg_g_' + g + '"></div></div>'
    h += '</div>'
    usuarios = Usuario.query.filter(Usuario.tipo != 'admin').order_by(Usuario.tipo, Usuario.nome).all()
    h += '<div class="painel"><h4>🙋 USUÁRIOS — grupo e status</h4>'
    if not usuarios:
        h += '<p style="color:#8fa3c0">Nenhum usuário cadastrado ainda.</p>'
    else:
        h += '<table class="tabela"><thead><tr><th>Nome</th><th>E-mail</th><th>Grupo</th><th>Ativo</th><th>Salvar</th></tr></thead><tbody>'
        for alvo in usuarios:
            h += ('<tr><td><b>' + alvo.nome + '</b><br><span style="color:#8fa3c0;font-size:11px">' + alvo.email + '</span></td>'
                  '<td><select id="grupo_' + str(alvo.id) + '">')
            for g in GRUPOS:
                sel = ' selected' if grupo_do_usuario(alvo) == g else ''
                h += '<option value="' + g + '"' + sel + '>' + GRUPO_LABEL.get(g, g) + '</option>'
            h += '</select></td>'
            h += '<td><input type="checkbox" id="ativo_' + str(alvo.id) + '" ' + ('checked' if alvo.ativo else '') + ' style="width:auto"></td>'
            h += '<td><button class="btn cinza" onclick="salvarUsuario(' + str(alvo.id) + ')">💾</button></td></tr>'
        h += '</tbody></table>'
    h += '</div>'
    h += ('<script>'
          'function salvarGrupo(g){var mods={};'
          'document.querySelectorAll("#mods_g_"+g+" input[data-mod]").forEach(function(cb){mods[cb.getAttribute("data-mod")]=cb.checked;});'
          'fetch("/api/admin/grupos/permissoes",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({grupo:g,permissoes:mods})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg_g_"+g);if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Permissões do grupo salvas!";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});}'
          'function salvarUsuario(uid){'
          'fetch("/api/admin/usuario/grupo",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({usuario_id:uid,grupo:document.getElementById("grupo_"+uid).value,'
          'ativo:document.getElementById("ativo_"+uid).checked})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){if(res.ok){alert("✅ Usuário atualizado!");}else{alert("❌ "+(res.j.erro||"Erro"));}});}</script>')
    return pagina(h, '/gerenciar')
    for alvo in usuarios:
        perms = {p.modulo: p.habilitado for p in Permissao.query.filter_by(usuario_id=alvo.id).all()}
        h += '<div class="painel">'
        h += '<div class="status" style="justify-content:space-between;align-items:center;margin-bottom:12px">'
        h += '<div><b>' + alvo.nome + '</b> <span class="pill ' + alvo.tipo + '">' + alvo.tipo + '</span><br>'
        h += '<span style="color:#8fa3c0;font-size:12px">' + alvo.email + '</span></div>'
        h += '<div class="status"><label style="font-size:12px"><input type="checkbox" id="ativo_' + str(alvo.id) + '" ' + ('checked' if alvo.ativo else '') + ' style="width:auto"> Ativo</label>'
        if alvo.tipo == 'candidato':
            h += ' <a class="btn cinza" href="/editar-candidato/' + str(alvo.id) + '">✏️ Editar</a>'
        h += '</div></div>'
        h += '<div class="status" id="mods_' + str(alvo.id) + '">'
        for mod in MODULOS_GERENCIAVEIS:
            checked = ' checked' if perms.get(mod, mod in PERMISSOES_PADRAO.get(alvo.tipo, [])) else ''
            h += ('<label style="font-size:12px;display:flex;align-items:center;gap:4px;background:rgba(15,33,64,.5);'
                  'padding:4px 8px;border-radius:6px"><input type="checkbox" data-mod="' + mod + '"' + checked + ' style="width:auto"> '
                  + mod.replace('_', ' ').title() + '</label>')
        h += '</div>'
        h += '<button class="btn verde" style="margin-top:12px" onclick="salvarPerm(' + str(alvo.id) + ')">💾 Salvar permissões de ' + alvo.nome.split()[0] + '</button>'
        h += '<div class="mensagem" id="msg_' + str(alvo.id) + '"></div></div>'
    h += ('<script>function salvarPerm(uid){var mods={};'
          'document.querySelectorAll("#mods_"+uid+" input[data-mod]").forEach(function(cb){mods[cb.getAttribute("data-mod")]=cb.checked;});'
          'mods["_ativo"]=document.getElementById("ativo_"+uid)?document.getElementById("ativo_"+uid).checked:true;'
          'fetch("/api/admin/permissoes",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({usuario_id:uid,permissoes:mods})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg_"+uid);if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Permissões salvas!";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});}</script>')
    return pagina(h, '/gerenciar')

# ================= CENTRAL DE ENTREVISTAS =================
@app.route('/entrevistas')
@gestor_required
def entrevistas():
    vaga_id = request.args.get('vaga', type=int)
    vagas = Vaga.query.order_by(Vaga.id.desc()).all()
    v = Vaga.query.get(vaga_id) if vaga_id else (vagas[0] if vagas else None)
    h = '<h1>Central de Entrevistas <span>// 🎥</span></h1>'
    h += '<p class="sub">Agende, confirme e avalie entrevistas de cada vaga.</p>'
    if not vagas:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma vaga cadastrada.</p></div>'
        return pagina(h, '/entrevistas')
    h += '<div class="caixa-busca"><select id="selvaga" onchange="location.href=\'/entrevistas?vaga=\'+this.value">'
    for vg in vagas:
        sel = ' selected' if v and vg.id == v.id else ''
        h += '<option value="' + str(vg.id) + '"' + sel + '>💼 ' + vg.titulo + '</option>'
    h += '</select><a class="btn cinza" href="/pipeline?vaga=' + str(v.id) + '">📋 Pipeline</a></div>'
    ent_list = Entrevista.query.filter_by(vaga_id=v.id).order_by(Entrevista.data_hora.desc()).all()
    if not ent_list:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma entrevista agendada para esta vaga. '
        h += 'Agende direto pelo <a class="link" href="/pipeline?vaga=' + str(v.id) + '">Pipeline</a> (botão 🎥 no cartão) ou pelo <a class="link" href="/gerenciar">Gerenciamento</a>.</p></div>'
    else:
        h += '<div class="painel"><table class="tabela"><thead><tr><th>Candidato</th><th>Data/Hora</th><th>Tipo</th><th>Status</th><th>Nota</th><th>Ações</th></tr></thead><tbody>'
        for e in ent_list:
            cand = Usuario.query.get(e.candidato_id)
            nota = ('<b style="color:#22d3ee">' + str(int(e.nota)) + '/10</b>') if e.nota is not None else '-'
            acoes = ''
            if e.status == 'agendada':
                acoes += '<a class="kbtn" href="/entrevista/' + str(e.id) + '/avaliar">⭐ Avaliar</a>'
            if e.status in ('agendada', 'confirmada'):
                acoes += '<a class="kbtn" href="/api/entrevistas/' + str(e.id) + '/status?novo=realizada">✅ Realizar</a>'
                acoes += '<a class="kbtn" href="/api/entrevistas/' + str(e.id) + '/status?novo=cancelada">❌ Cancelar</a>'
            if e.status == 'agendada':
                acoes += '<a class="kbtn" href="/api/entrevistas/' + str(e.id) + '/status?novo=confirmada">✔ Confirmada</a>'
            if e.comentario:
                acoes += '<span style="color:#8fa3c0;font-size:11px">💬 ' + e.comentario[:50] + '</span>'
            h += ('<tr><td><b>' + (cand.nome if cand else '-') + '</b></td>'
                  '<td>' + e.data_hora.strftime('%d/%m/%Y %H:%M') + '</td>'
                  '<td>' + (e.tipo or '-') + '</td>'
                  '<td><span class="pill ' + e.status + '">' + e.status + '</span></td>'
                  '<td>' + nota + '</td>'
                  '<td><div class="kbtns">' + acoes + '</div></td></tr>')
        h += '</tbody></table></div>'
    return pagina(h, '/entrevistas')

@app.route('/entrevista/<int:eid>/avaliar')
@gestor_required
def avaliar_entrevista(eid):
    e = Entrevista.query.get(eid)
    if not e:
        return pagina('<h1>Entrevista não encontrada</h1>', '/entrevistas')
    cand = Usuario.query.get(e.candidato_id)
    v = Vaga.query.get(e.vaga_id)
    h = '<h1>⭐ Avaliar Entrevista <span>// ' + (cand.nome if cand else '') + '</span></h1>'
    h += '<p class="sub">💼 ' + (v.titulo if v else '') + ' • ' + e.data_hora.strftime('%d/%m/%Y %H:%M') + '</p>'
    h += '<div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Nota (0 a 10) *</label><input id="nota" type="number" min="0" max="10" step="1" required placeholder="ex: 8">'
    h += '<label>Comentário</label><textarea id="comentario" rows="4" placeholder="Impressões sobre o candidato..."></textarea>'
    h += '<div style="margin-top:16px"><button class="btn verde" type="submit">Salvar avaliação</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/entrevistas/' + str(eid) + '/avaliar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({nota:document.getElementById("nota").value,comentario:document.getElementById("comentario").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Avaliação salva! <a class=link href=/entrevistas>Voltar para entrevistas</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/entrevistas')

@app.route('/minhas-entrevistas')
@login_required
def minhas_entrevistas():
    u = usuario_atual()
    ent_list = Entrevista.query.filter_by(candidato_id=u.id).order_by(Entrevista.data_hora.desc()).all()
    h = '<h1>Minhas Entrevistas <span>// 🎥</span></h1>'
    h += '<p class="sub">Acompanhe as entrevistas agendadas para você.</p>'
    if not ent_list:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma entrevista agendada ainda. '
        h += 'Quando uma empresa marcar uma entrevista para você, ela aparecerá aqui. <a class="link" href="/vagas">Ver vagas →</a></p></div>'
    else:
        for e in ent_list:
            v = Vaga.query.get(e.vaga_id)
            status_badge = '<span class="pill ' + e.status + '">' + e.status + '</span>'
            link_acao = ''
            if e.status == 'agendada':
                link_acao = '<a class="kbtn verde" href="/api/entrevistas/' + str(e.id) + '/status?novo=confirmada">✔ Confirmar presença</a>'
            if e.link:
                link_acao += ' <a class="kbtn" href="' + e.link + '" target="_blank">🔗 Link da sala</a>'
            if e.status == 'realizada' and e.nota is not None:
                link_acao += ' <span class="pill realizada">⭐ Nota: ' + str(int(e.nota)) + '/10</span>'
            h += ('<div class="painel"><div class="status" style="justify-content:space-between;flex-wrap:wrap">'
                  '<div><h3>🎥 ' + (v.titulo if v else 'Entrevista') + '</h3>'
                  '<p style="color:#8fa3c0;font-size:13px;margin-top:6px">📅 <b>' + e.data_hora.strftime('%d/%m/%Y às %H:%M') + '</b> • Tipo: ' + (e.tipo or '-') + ' • Empresa: ' + (v.empresa if v else '-') + '</p>'
                  + (('<p style="color:#8fa3c0;font-size:12px;margin-top:4px">💬 ' + e.comentario + '</p>') if e.comentario else '') + '</div>'
                  '<div style="text-align:right">' + status_badge + '<br><br>' + link_acao + '</div></div></div>')
    return pagina(h, '/minhas-entrevistas')

# ================= MENSAGENS (CHAT) =================
@app.route('/mensagens')
@login_required
def mensagens():
    u = usuario_atual()
    if not tem_permissao(u, 'mensagens'):
        return redirect(url_for('painel'))
    convs = Conversa.query.filter((Conversa.candidato_id == u.id) | (Conversa.empresa_id == u.id)).order_by(Conversa.id.desc()).all()
    h = '<h1>Mensagens <span>// ' + u.nome + '</span></h1>'
    h += '<p class="sub">Conversas entre candidatos e empresas. Clique para abrir.</p>'
    if not convs:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma conversa ainda. '
        if u.tipo == 'candidato':
            h += '<a class="link" href="/vagas">Candidatar-se a uma vaga →</a></p></div>'
        else:
            h += 'Clique no botão 💬 no <a class="link" href="/pipeline">Pipeline</a> ou no <a class="link" href="/vagas/1/ranking">Ranking</a> para iniciar uma conversa com o candidato.</p></div>'
        return pagina(h, '/mensagens')
    for c in convs:
        v = Vaga.query.get(c.vaga_id)
        outro_id = c.empresa_id if u.id == c.candidato_id else c.candidato_id
        outro = Usuario.query.get(outro_id)
        nao_lidas = Mensagem.query.filter_by(conversa_id=c.id, lida=False).filter(Mensagem.remetente_id != u.id).count()
        badge = ' <span class="pill nv">' + str(nao_lidas) + ' novas</span>' if nao_lidas else ''
        h += ('<a href="/mensagens/' + str(c.id) + '" style="text-decoration:none"><div class="conv">'
              '<div><b>💬 ' + (outro.nome if outro else 'Conversa') + '</b>'
              '<div style="color:#8fa3c0;font-size:12px">📌 ' + (v.titulo if v else 'Vaga') + ' • ' + (v.empresa if v else '') + '</div></div>'
              '<div style="text-align:right;font-size:12px;color:#8fa3c0">abrir →' + badge + '</div></div></a>')
    return pagina(h, '/mensagens')

@app.route('/conversa/<int:vid>')
@login_required
def abrir_conversa(vid):
    u = usuario_atual()
    v = Vaga.query.get(vid)
    if not v:
        return pagina('<h1>Vaga não encontrada</h1>', '/vagas')
    if u.tipo == 'candidato':
        c = Conversa.query.filter_by(vaga_id=vid, candidato_id=u.id).first()
        if not c:
            emp = usuario_empresa_da_vaga(v)
            if not emp:
                return pagina('<h1>Sem empresa responsável</h1><p class="sub">Entre como empresa para iniciar conversas.</p>', '/vagas')
            c = Conversa(vaga_id=vid, candidato_id=u.id, empresa_id=emp.id)
            db.session.add(c)
            db.session.commit()
        return redirect(url_for('chat', cid=c.id))
    return redirect(url_for('mensagens'))

@app.route('/conversa-iniciar')
@login_required
def conversa_iniciar():
    u = usuario_atual()
    vaga_id = request.args.get('vaga', type=int)
    cand_id = request.args.get('candidato', type=int)
    v = Vaga.query.get(vaga_id)
    c_user = Usuario.query.get(cand_id)
    if not v or not c_user or c_user.tipo != 'candidato':
        return redirect(url_for('vagas'))
    if u.tipo == 'candidato':
        return redirect(url_for('abrir_conversa', vid=vaga_id))
    emp = u if u.tipo == 'empresa' else (usuario_empresa_da_vaga(v) or u)
    conv = Conversa.query.filter_by(vaga_id=vaga_id, candidato_id=cand_id).first()
    if not conv:
        conv = Conversa(vaga_id=vaga_id, candidato_id=cand_id, empresa_id=emp.id)
        db.session.add(conv)
        db.session.commit()
    return redirect(url_for('chat', cid=conv.id))

@app.route('/mensagens/<int:cid>')
@login_required
def chat(cid):
    u = usuario_atual()
    c = Conversa.query.get(cid)
    if not c:
        return pagina('<h1>Conversa não encontrada</h1>', '/mensagens')
    if u.id not in (c.candidato_id, c.empresa_id) and u.tipo != 'admin':
        return pagina('<h1>Acesso restrito</h1><p class="sub">Esta conversa não é sua.</p>', '/mensagens')
    v = Vaga.query.get(c.vaga_id)
    outro_id = c.empresa_id if u.id == c.candidato_id else c.candidato_id
    outro = Usuario.query.get(outro_id)
    for m in Mensagem.query.filter_by(conversa_id=cid, lida=False).filter(Mensagem.remetente_id != u.id).all():
        m.lida = True
    db.session.commit()
    msgs = Mensagem.query.filter_by(conversa_id=cid).order_by(Mensagem.id).all()
    h = '<h1>💬 ' + (outro.nome if outro else 'Conversa') + ' <span>// Chat</span></h1>'
    h += '<p class="sub">📌 ' + (v.titulo if v else 'Vaga') + ' • ' + (v.empresa if v else '') + ' • <a class="link" href="/mensagens">← Voltar</a></p>'
    h += '<div class="painel"><div class="chatbox" id="chat">'
    for m in msgs:
        cls = 'minha' if m.remetente_id == u.id else 'dela'
        autor = Usuario.query.get(m.remetente_id)
        hora = m.criada_em.strftime('%H:%M') if m.criada_em else ''
        h += ('<div class="bubble ' + cls + '">' + (m.texto or '') + ''
              '<span class="hora">' + (autor.nome.split()[0] if autor and autor.nome else '') + ' • ' + hora + '</span></div>')
    h += '</div>'
    h += '<div class="chatbar"><input id="texto" placeholder="Escreva sua mensagem..." onkeydown="if(event.key===\'Enter\')enviar()">'
    h += '<button class="btn" onclick="enviar()">Enviar ➤</button></div></div>'
    h += ('<script>var cid=' + str(cid) + ';'
          'function enviar(){var t=document.getElementById("texto").value;if(!t.trim()){return;}'
          'fetch("/api/conversas/' + cid + '/mensagens",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({texto:t})})'
          '.then(function(r){return r.json();}).then(function(j){if(j.ok){document.getElementById("texto").value="";atualizar();}});}'
          'function atualizar(){fetch("/api/conversas/' + cid + '/mensagens").then(function(r){return r.json();}).then(function(j){'
          'var box=document.getElementById("chat");var html="";for(var i=0;i<j.mensagens.length;i++){var m=j.mensagens[i];'
          'var cls=(m.remetente_id===' + str(u.id) + ')?"minha":"dela";'
          'html+="<div class=\"bubble "+cls+"\">"+m.texto+"<span class=\"hora\">"+m.autor+" • "+m.hora+"</span></div>";}'
          'box.innerHTML=html;box.scrollTop=box.scrollHeight;});}'
          'setInterval(atualizar,3000);setTimeout(atualizar,500);</script>')
    return pagina(h, '/mensagens')

# ================= PIPELINE (KANBAN) =================
@app.route('/pipeline')
@gestor_required
def pipeline():
    vaga_id = request.args.get('vaga', type=int)
    vagas = Vaga.query.order_by(Vaga.id.desc()).all()
    v = Vaga.query.get(vaga_id) if vaga_id else (vagas[0] if vagas else None)
    h = '<h1>Pipeline de Recrutamento <span>// Kanban</span></h1>'
    h += '<p class="sub">Acompanhe cada candidato na jornada: Triagem → Entrevista → Proposta → Contratado.</p>'
    if not vagas:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma vaga cadastrada. <a class="link" href="/cadastrar-vaga">Publicar uma vaga →</a></p></div>'
        return pagina(h, '/pipeline')
    h += '<div class="caixa-busca"><select id="selvaga" onchange="location.href=\'/pipeline?vaga=\'+this.value">'
    for vg in vagas:
        sel = ' selected' if v and vg.id == v.id else ''
        h += '<option value="' + str(vg.id) + '"' + sel + '>💼 ' + vg.titulo + '</option>'
    h += '</select><a class="btn cinza" href="/vagas/' + str(v.id) + '/ranking">🏆 Ranking</a>'
    h += '<a class="btn cinza" href="/entrevistas?vaga=' + str(v.id) + '">🎥 Entrevistas</a>'
    h += '<a class="btn cinza" href="/vagas/' + str(v.id) + '">📋 Detalhes</a></div>'
    cands = Candidatura.query.filter_by(vaga_id=v.id).all()
    por_etapa = {e: [] for e in ETAPAS}
    for c in cands:
        et = c.etapa if c.etapa in por_etapa else 'triagem'
        por_etapa[et].append(c)
    h += '<div class="kanban">'
    for et in ETAPAS:
        nome_et, cor = ETAPAS_INFO[et]
        lista = por_etapa[et]
        h += '<div class="kcol"><h4><span style="color:' + cor + '">●</span> ' + nome_et + ' <span style="color:' + cor + '">' + str(len(lista)) + '</span></h4>'
        for c in lista:
            cand = Usuario.query.get(c.candidato_id)
            idx = ETAPAS.index(et)
            btns = ''
            if idx > 0:
                btns += '<button class="kbtn" onclick="mover(' + str(c.id) + ',\'' + ETAPAS[idx - 1] + '\')">◀ ' + ETAPAS_INFO[ETAPAS[idx - 1]][0] + '</button>'
            if idx < len(ETAPAS) - 1:
                btns += '<button class="kbtn verde" onclick="mover(' + str(c.id) + ',\'' + ETAPAS[idx + 1] + '\')">' + ETAPAS_INFO[ETAPAS[idx + 1]][0] + ' ▶</button>'
            btns += '<a class="kbtn" href="/conversa-iniciar?vaga=' + str(v.id) + '&candidato=' + str(c.candidato_id) + '">💬</a>'
            ent = Entrevista.query.filter_by(vaga_id=v.id, candidato_id=c.candidato_id).order_by(Entrevista.id.desc()).first()
            if ent:
                btns += '<a class="kbtn roxo" href="/entrevistas?vaga=' + str(v.id) + '">🎥 ' + ent.status + '</a>'
            else:
                btns += '<a class="kbtn roxo" href="/agendar-entrevista?candidatura=' + str(c.id) + '">🎥 Agendar</a>'
            cor_score = '#10b981' if c.match_score >= 80 else ('#f59e0b' if c.match_score >= 65 else '#ef4444')
            h += ('<div class="kcard"><b>' + (cand.nome if cand else 'Candidato') + '</b>'
                  '<div class="meta">Match: <b style="color:' + cor_score + '">' + str(int(c.match_score or 0)) + '%</b></div>'
                  '<div class="meta">' + (cand.email if cand else '') + '</div>'
                  '<div class="kbtns">' + btns + '</div></div>')
        h += '</div>'
    h += '</div>'
    h += ('<script>function mover(cid,eta){'
          'fetch("/api/pipeline/"+cid+"/etapa",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({etapa:eta})})'
          '.then(function(r){return r.json();}).then(function(j){if(j.ok){location.reload();}else{alert(j.erro||"Erro");}});}</script>')
    return pagina(h, '/pipeline')

@app.route('/agendar-entrevista')
@gestor_required
def agendar_entrevista():
    c = Candidatura.query.get(request.args.get('candidatura', type=int))
    if not c:
        return pagina('<h1>Candidatura não encontrada</h1>', '/pipeline')
    v = Vaga.query.get(c.vaga_id)
    cand = Usuario.query.get(c.candidato_id)
    h = '<h1>🎥 Agendar Entrevista <span>// ' + (cand.nome if cand else '') + '</span></h1>'
    h += '<p class="sub">💼 ' + (v.titulo if v else '') + ' • ' + (v.empresa if v else '') + '</p>'
    h += '<div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Data *</label><input id="data" type="date" required value="' + (datetime.utcnow() + timedelta(days=2)).strftime('%Y-%m-%d') + '">'
    h += '<label>Hora *</label><input id="hora" type="time" required value="14:00">'
    h += '<label>Tipo</label><select id="tipo"><option value="Video">🎥 Vídeo</option><option value="Presencial">🏢 Presencial</option><option value="Telefonica">📞 Telefônica</option></select>'
    h += '<label>Link da sala (opcional)</label><input id="link" placeholder="https://meet.google.com/...">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Agendar entrevista</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/entrevistas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({candidatura:' + str(c.id) + ',data:document.getElementById("data").value,'
          'hora:document.getElementById("hora").value,tipo:document.getElementById("tipo").value,'
          'link:document.getElementById("link").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Entrevista agendada! <a class=link href=/entrevistas>Ver central →</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/entrevistas')

# ================= MEU PAINEL =================
@app.route('/painel')
@login_required
def painel():
    u = usuario_atual()
    if not tem_permissao(u, 'painel'):
        return redirect(url_for('menu'))
    h = '<h1>Meu Painel <span>// ' + u.nome + '</span></h1><p class="sub">Acompanhe suas atividades no ecossistema.</p>'
    if u.tipo == 'candidato':
        p = Perfil.query.filter_by(usuario_id=u.id).first()
        if p and p.skills:
            h += '<div class="painel"><h4>Minhas Skills</h4><div class="status">'
            for sk in [s.strip() for s in p.skills.split(',') if s.strip()]:
                h += '<span class="pill candidato">' + sk + '</span>'
            h += ' <a class="link" href="/perfil">editar →</a></div></div>'
        ents = Entrevista.query.filter_by(candidato_id=u.id).order_by(Entrevista.data_hora.desc()).all()
        h += '<div class="painel"><h4>🎥 Minhas Entrevistas</h4>'
        if ents:
            for e in ents[:3]:
                v = Vaga.query.get(e.vaga_id)
                h += ('<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(28,47,74,.5)">'
                      '<div><b>' + (v.titulo if v else 'Vaga') + '</b> • ' + (v.empresa if v else '') + '<br>'
                      '<span style="color:#8fa3c0;font-size:12px">📅 ' + e.data_hora.strftime('%d/%m/%Y %H:%M') + '</span></div>'
                      '<span class="pill ' + e.status + '">' + e.status + '</span></div>')
            h += '<p style="margin-top:10px"><a class="link" href="/minhas-entrevistas">Ver todas →</a></p>'
        else:
            h += '<p style="color:#8fa3c0">Nenhuma entrevista agendada ainda.</p>'
        h += '</div>'
        cands = Candidatura.query.filter_by(candidato_id=u.id).order_by(Candidatura.id.desc()).all()
        h += '<div class="painel"><h4>Minhas Candidaturas</h4>'
        if cands:
            h += '<table class="tabela"><thead><tr><th>Vaga</th><th>Empresa</th><th>Match</th><th>Etapa</th><th>Status</th><th>Chat</th><th>Data</th></tr></thead><tbody>'
            for c in cands:
                v = Vaga.query.get(c.vaga_id)
                et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
                conv = Conversa.query.filter_by(vaga_id=c.vaga_id, candidato_id=u.id).first()
                chat_link = ('<a class="link" href="/mensagens/' + str(conv.id) + '">💬 Conversar</a>' if conv
                             else '<a class="link" href="/conversa/' + str(c.vaga_id) + '">💬 Iniciar</a>')
                h += ('<tr><td><b><a class="link" href="/vagas/' + str(v.id) + '">' + (v.titulo if v else 'Vaga') + '</a></b></td><td>' + (v.empresa if v else '-') + '</td>'
                      '<td><b style="color:#22d3ee">' + str(int(c.match_score)) + '%</b></td>'
                      '<td><span class="pill ' + et + '">' + ETAPAS_INFO[et][0] + '</span></td>'
                      '<td><span class="pill ' + c.status + '">' + c.status + '</span></td>'
                      '<td>' + chat_link + '</td>'
                      '<td>' + c.criada_em.strftime('%d/%m/%Y') + '</td></tr>')
            h += '</tbody></table>'
        else:
            h += '<p style="color:#8fa3c0">Você ainda não se candidatou. <a class="link" href="/vagas">Ver vagas abertas →</a></p>'
        h += '</div>'
        h += '<div class="painel"><h4>Estatísticas</h4><div class="status">'
        h += '<div class="item"><span class="dot ciano"></span> Candidaturas: <b>' + str(len(cands)) + '</b></div>'
        h += '<div class="item"><span class="dot roxo"></span> Entrevistas: <b>' + str(len(ents)) + '</b></div>'
        h += '<div class="item"><span class="dot"></span> Vagas abertas: <b>' + str(Vaga.query.filter_by(status='aberta').count()) + '</b></div>'
        scores = [c.match_score or 0 for c in cands]
        h += '<div class="item"><span class="dot roxo"></span> Match médio: <b>' + (str(int(sum(scores)/len(scores))) + '%' if scores else '—') + '</b></div>'
        h += '</div></div>'
    elif u.tipo == 'empresa':
        emp = Empresa.query.filter_by(usuario_id=u.id).first()
        h += '<div class="painel"><h4>Perfil da Empresa</h4>'
        if emp:
            h += '<p style="font-size:14px"><b>' + emp.razao_social + '</b> • ' + (emp.setor or '-') + ' • ' + (emp.porte or '-') + '</p>'
        else:
            h += '<p style="color:#8fa3c0">Complete seu perfil: <a class="link" href="/cadastrar-empresa">Cadastrar Empresa →</a></p>'
        h += '</div>'
        vagas = Vaga.query.filter_by(empresa=emp.razao_social if emp else u.nome).all()
        h += '<div class="painel"><h4>Minhas Vagas</h4>'
        if vagas:
            h += '<table class="tabela"><thead><tr><th>Vaga</th><th>Nível</th><th>Candidaturas</th><th>Pipeline</th><th>Ranking</th><th>Status</th></tr></thead><tbody>'
            for v in vagas:
                total = Candidatura.query.filter_by(vaga_id=v.id).count()
                h += ('<tr><td><b><a class="link" href="/vagas/' + str(v.id) + '">' + v.titulo + '</a></b></td><td>' + (v.nivel_codigo or '-') + '</td>'
                      '<td>' + str(total) + '</td>'
                      '<td><a class="link" href="/pipeline?vaga=' + str(v.id) + '">ver kanban →</a></td>'
                      '<td><a class="link" href="/vagas/' + str(v.id) + '/ranking">ver ranking →</a></td>'
                      '<td><span class="pill ' + v.status + '">' + v.status + '</span></td></tr>')
            h += '</tbody></table>'
        else:
            h += '<p style="color:#8fa3c0">Nenhuma vaga publicada. <a class="link" href="/cadastrar-vaga">Publicar vaga →</a></p>'
        h += '</div>'
        h += '<div class="painel"><h4>Gestão</h4><div class="status">'
        h += '<a class="btn" href="/cadastrar-vaga">➕ Publicar Vaga</a> '
        h += '<a class="btn" href="/pipeline">📋 Pipeline</a> '
        h += '<a class="btn" href="/entrevistas">🎥 Entrevistas</a> '
        h += '<a class="btn" href="/mensagens">💬 Mensagens</a> '
        h += '<a class="btn cinza" href="/importar-plano">📥 Importar Plano PCS</a>'
        h += '</div></div>'
    else:
        h += '<div class="painel"><h4>Visão Geral (Administrador)</h4><div class="status">'
        h += '<div class="item"><span class="dot"></span> Candidatos: <b>' + str(Usuario.query.filter_by(tipo='candidato').count()) + '</b></div>'
        h += '<div class="item"><span class="dot ciano"></span> Empresas: <b>' + str(Usuario.query.filter_by(tipo='empresa').count()) + '</b></div>'
        h += '<div class="item"><span class="dot roxo"></span> Vagas: <b>' + str(Vaga.query.count()) + '</b></div>'
        h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(Candidatura.query.count()) + '</b></div>'
        h += '<div class="item"><span class="dot ciano"></span> Conversas: <b>' + str(Conversa.query.count()) + '</b></div>'
        h += '<div class="item"><span class="dot roxo"></span> Entrevistas: <b>' + str(Entrevista.query.count()) + '</b></div>'
        h += '</div></div>'
        h += '<div class="painel"><h4>Atalhos</h4><div class="status">'
        h += '<a class="btn" href="/cadastrar-vaga">➕ Publicar Vaga</a> '
        h += '<a class="btn" href="/cadastrar-candidato">👤➕ Cadastrar Candidato</a> '
        h += '<a class="btn" href="/gerenciar">⚙️ Gerenciar Usuários</a> '
        h += '<a class="btn" href="/pipeline">📋 Pipeline</a> '
        h += '<a class="btn" href="/entrevistas">🎥 Entrevistas</a> '
        h += '<a class="btn" href="/mensagens">💬 Mensagens</a> '
        h += '<a class="btn verde" href="/importar-plano">📥 Importar Plano PCS</a> '
        h += '<a class="btn cinza" href="/cadastrar-empresa">🏢 Cadastrar Empresa</a> '
        h += '<a class="btn cinza" href="/analytics">📈 Analytics</a>'
        h += '</div></div>'
        candidatos = Usuario.query.filter_by(tipo='candidato').order_by(Usuario.nome).all()
        if candidatos:
            h += '<div class="painel"><h4>👤 Candidatos (editar / agendar)</h4>'
            h += '<table class="tabela"><thead><tr><th>Nome</th><th>E-mail</th><th>Status</th><th>Ações</th></tr></thead><tbody>'
            for cand in candidatos:
                h += ('<tr><td><b>' + cand.nome + '</b></td><td>' + cand.email + '</td>'
                      '<td><span class="pill ' + ('candidato' if cand.ativo else 'fechada') + '">' + ('Ativo' if cand.ativo else 'Inativo') + '</span></td>'
                      '<td><a class="btn cinza" href="/editar-candidato/' + str(cand.id) + '">✏️ Editar / Agendar</a></td></tr>')
            h += '</tbody></table></div>'
    return pagina(h, '/painel')

# ================= PAGINAS PUBLICAS =================
@app.route('/')
def menu():
    cards = [
        ('🧠', 'Recrutamento Inteligente', 'IA generativa, matching preditivo e triagem NLP', '#3b82f6', '/recrutamento'),
        ('👤', 'Candidatos', 'Perfil com skills, match score e candidaturas', '#10b981', '/candidatos'),
        ('🏢', 'Empresas', 'ATS inteligente, employer branding e talent pool', '#f59e0b', '/empresas'),
        ('📊', 'Plano de Cargos e Salários', 'Níveis Júnior a Fellow, faixas e promoções', '#a855f7', '/pcs'),
        ('📡', 'Conectividade', 'Vídeo, WhatsApp, e-mail e chat em tempo real', '#22d3ee', '/conectividade'),
        ('💼', 'Vagas', 'Oportunidades abertas com busca, detalhe e ranking', '#ef4444', '/vagas'),
        ('📈', 'Analytics', 'People analytics, KPIs e dashboards', '#f97316', '/analytics'),
        ('🎯', 'Experiência', 'Onboarding, mentoria, feedback e comunidade', '#14b8a6', '/experiencia'),
        ('🚀', 'Inovação', 'Web3, Skills DNA, VR e recrutamento assíncrono', '#8b5cf6', '/inovacao'),
    ]
    grade = ''
    for icone, titulo, desc, cor, href in cards:
        grade += ('<a href="' + href + '" style="text-decoration:none"><div class="card">'
                  '<div class="icone" style="background:' + cor + '22">' + icone + '</div>'
                  '<h3>' + titulo + '</h3><p>' + desc + '</p></div></a>')
    h = '<h1>Menu Principal <span>// Ecossistema de RH Inovador</span></h1>'
    h += '<p class="sub">Plataforma completa de procura e oferta de empregos — tudo que há de mais inovador.</p>'
    h += '<div class="grade">' + grade + '</div>'
    h += '<div class="painel"><h4>Status do Servidor</h4><div class="status">'
    h += '<div class="item"><span class="dot"></span> Servidor Online</div>'
    h += '<div class="item"><span class="dot ciano"></span> Conexões Ativas: <b id="conn2">0/' + str(MAX_CONEXOES) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> Agentes Autônomos: <b>5 ativos</b></div>'
    h += '<div class="item"><span class="dot"></span> Módulos: <b>14</b></div>'
    h += '</div></div>'
    h += '<script>setInterval(function(){fetch("/api/health").then(function(r){return r.json();}).then(function(d){'
    h += 'var el=document.getElementById("conn2");if(el)el.textContent=d.conexoes_ativas+"/"+d.conexoes_maximas;}).catch(function(){});},3000);</script>'
    return pagina(h, '/')

@app.route('/pcs')
def pcs():
    trilhas = Trilha.query.all()
    niveis = Nivel.query.all()
    h = '<h1>Plano de Cargos e Salários <span>// PCS</span></h1>'
    h += '<p class="sub">' + str(len(trilhas)) + ' trilhas • ' + str(len(niveis)) + ' níveis • faixas salariais dinâmicas'
    u = usuario_atual()
    if u and tem_permissao(u, 'importar_plano'):
        h += ' • <a class="link" href="/importar-plano">📥 Importar/Atualizar plano</a>'
    h += '</p>'
    for t in trilhas:
        qtd = Nivel.query.filter_by(trilha_id=t.id).count()
        h += '<div class="painel"><h4>🧭 ' + t.nome + ' • ' + str(qtd) + ' níveis</h4><p style="color:#8fa3c0;font-size:13px;margin-bottom:12px">' + (t.descricao or '') + '</p>'
        h += '<table class="tabela"><thead><tr><th>Código</th><th>Nível</th><th>Autonomia</th><th>Impacto</th><th>Faixa Salarial</th></tr></thead><tbody>'
        for n in Nivel.query.filter_by(trilha_id=t.id).order_by(Nivel.ordem).all():
            h += ('<tr><td><b>' + n.codigo + '</b></td><td>' + n.nome + '</td><td>' + (n.autonomia or '-') + '</td>'
                  '<td>' + (n.impacto or '-') + '</td><td><b style="color:#22d3ee">' + texto_int(n.salario_min) + ' – ' + texto_int(n.salario_max) + '</b></td></tr>')
        h += '</tbody></table></div>'
    return pagina(h, '/pcs')

@app.route('/trilhas')
def trilhas():
    h = '<h1>Trilhas de Carreira <span>// Estrutura</span></h1><p class="sub">Caminhos de desenvolvimento profissional</p>'
    for t in Trilha.query.all():
        ns = Nivel.query.filter_by(trilha_id=t.id).order_by(Nivel.ordem).all()
        seq = ' → '.join(n.codigo for n in ns)
        h += '<div class="painel"><h4>🧭 ' + t.nome + '</h4><p style="color:#8fa3c0;font-size:13px;margin-bottom:10px">' + (t.descricao or '') + '</p><p style="font-size:14px"><b>' + seq + '</b></p></div>'
    return pagina(h, '/pcs')

@app.route('/vagas')
def vagas():
    q = (request.args.get('q') or '').strip().lower()
    nivel = (request.args.get('nivel') or '').strip()
    regime = (request.args.get('regime') or '').strip()
    query = Vaga.query.filter_by(status='aberta')
    if q:
        query = query.filter((Vaga.titulo.ilike('%' + q + '%')) | (Vaga.empresa.ilike('%' + q + '%')) | (Vaga.descricao.ilike('%' + q + '%')))
    if nivel:
        query = query.filter_by(nivel_codigo=nivel)
    if regime:
        query = query.filter_by(regime=regime)
    lista = query.order_by(Vaga.id.desc()).all()
    u = usuario_atual()
    h = '<h1>Vagas <span>// Oportunidades</span></h1>'
    h += '<p class="sub">' + str(len(lista)) + ' vagas abertas' + (' • filtro: ' + q if q else '') + '</p>'
    h += '<div class="caixa-busca">'
    h += '<input id="q" placeholder="🔍 Buscar por título, empresa..." value="' + q + '" onkeydown="if(event.key===\'Enter\')aplicar()">'
    h += '<select id="nivel" onchange="aplicar()"><option value="">Todos os níveis</option>'
    for cod in sorted(set(n.codigo for n in Nivel.query.all())):
        sel = ' selected' if cod == nivel else ''
        h += '<option value="' + cod + '"' + sel + '>' + cod + '</option>'
    h += '</select>'
    h += '<select id="regime" onchange="aplicar()"><option value="">Todos os regimes</option>'
    for r in ['Remoto', 'Híbrido', 'Presencial']:
        sel = ' selected' if r == regime else ''
        h += '<option value="' + r + '"' + sel + '>' + r + '</option>'
    h += '</select>'
    h += '<button class="btn cinza" onclick="aplicar()">Filtrar</button>'
    h += '<a class="btn" href="/vagas">Limpar</a>'
    h += '</div>'
    h += ('<script>function aplicar(){var p=new URLSearchParams();'
          'var qv=document.getElementById("q").value;if(qv)p.set("q",qv);'
          'var nv=document.getElementById("nivel").value;if(nv)p.set("nivel",nv);'
          'var rv=document.getElementById("regime").value;if(rv)p.set("regime",rv);'
          'location.href="/vagas"+(p.toString()?"?"+p.toString():"");}</script>')
    if u and tem_permissao(u, 'cadastrar_vaga'):
        h += '<div class="painel"><p><a class="btn cinza" href="/cadastrar-vaga">➕ Nova Vaga</a></p></div>'
    if not lista:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma vaga encontrada com esses filtros.</p></div>'
    for v in lista:
        reqs = [r.skill for r in Requisito.query.filter_by(vaga_id=v.id).all()]
        req_html = ''
        if reqs:
            req_html = '<p style="color:#8fa3c0;font-size:12px;margin-top:6px">🎯 Requisitos: '
            req_html += ', '.join('<b>' + r + '</b>' for r in reqs) + '</p>'
        h += ('<div class="painel"><div class="status" style="justify-content:space-between;flex-wrap:wrap">'
              '<div><h3>💼 <a class="link" href="/vagas/' + str(v.id) + '">' + v.titulo + '</a></h3>'
              '<p style="color:#8fa3c0;font-size:13px;margin-top:6px">' + (v.descricao or '') + '</p>'
              '<p style="color:#8fa3c0;font-size:12px;margin-top:6px">🏢 ' + (v.empresa or '-') + ' • Nível <b>' + (v.nivel_codigo or '-') + '</b> • ' + (v.regime or '-') + ' • ' + (v.localizacao or '-') + '</p>'
              + req_html + '</div>'
              '<div style="text-align:right"><span class="pill ' + v.status + '">' + v.status + '</span><br><br>'
              '<a class="btn" href="/vagas/' + str(v.id) + '">📋 Detalhes</a> '
              '<a class="btn cinza" href="/vagas/' + str(v.id) + '/candidatar">📩 Candidatar-se</a></div></div></div>')
    return pagina(h, '/vagas')

@app.route('/vagas/<int:vid>')
def detalhe_vaga(vid):
    v = Vaga.query.get(vid)
    if not v:
        return pagina('<h1>Vaga não encontrada</h1><p class="sub"><a class="link" href="/vagas">← Voltar para vagas</a></p>', '/vagas')
    reqs = [r.skill for r in Requisito.query.filter_by(vaga_id=v.id).all()]
    total_cands = Candidatura.query.filter_by(vaga_id=v.id).count()
    h = '<h1>' + v.titulo + ' <span>// Detalhes</span></h1>'
    h += '<p class="sub"><a class="link" href="/vagas">← Voltar para vagas</a></p>'
    h += '<div class="painel"><h4>Informações da Vaga</h4>'
    h += '<table class="tabela"><tbody>'
    h += '<tr><td><b>🏢 Empresa</b></td><td>' + (v.empresa or '-') + '</td></tr>'
    h += '<tr><td><b>📊 Nível</b></td><td>' + (v.nivel_codigo or '-') + '</td></tr>'
    h += '<tr><td><b>💼 Regime</b></td><td>' + (v.regime or '-') + '</td></tr>'
    h += '<tr><td><b>📍 Localização</b></td><td>' + (v.localizacao or '-') + '</td></tr>'
    h += '<tr><td><b>💰 Salário</b></td><td><b style="color:#22d3ee">' + texto_int(v.salario_min) + ' – ' + texto_int(v.salario_max) + '</b></td></tr>'
    h += '<tr><td><b>📝 Descrição</b></td><td>' + (v.descricao or '-') + '</td></tr>'
    h += '<tr><td><b>🎯 Requisitos</b></td><td>' + (', '.join('<b>' + r + '</b>' for r in reqs) if reqs else '-') + '</td></tr>'
    h += '<tr><td><b>👥 Candidaturas</b></td><td>' + str(total_cands) + '</td></tr>'
    h += '<tr><td><b>📌 Status</b></td><td><span class="pill ' + v.status + '">' + v.status + '</span></td></tr>'
    h += '</tbody></table></div>'
    h += '<div class="status">'
    h += '<a class="btn" href="/vagas/' + str(vid) + '/candidatar">📩 Candidatar-se</a>'
    u = usuario_atual()
    if u and tem_permissao(u, 'mensagens'):
        h += '<a class="btn cinza" href="/conversa/' + str(vid) + '">💬 Falar com a empresa</a>'
    if u and u.tipo in ('admin', 'empresa'):
        h += '<a class="btn cinza" href="/vagas/' + str(vid) + '/ranking">🏆 Ver Ranking</a>'
        h += '<a class="btn cinza" href="/pipeline?vaga=' + str(vid) + '">📋 Ver Pipeline</a>'
        h += '<a class="btn cinza" href="/entrevistas?vaga=' + str(vid) + '">🎥 Entrevistas</a>'
    h += '</div>'
    return pagina(h, '/vagas')

@app.route('/vagas/<int:vid>/ranking')
@login_required
def ranking_vaga(vid):
    v = Vaga.query.get(vid)
    if not v:
        return pagina('<h1>Vaga não encontrada</h1>', '/vagas')
    u = usuario_atual()
    if u.tipo not in ('admin', 'empresa'):
        return pagina('<h1>Acesso restrito</h1><p class="sub">Somente empresas e administradores podem ver o ranking de candidatos.</p>', '/vagas')
    cands = Candidatura.query.filter_by(vaga_id=vid).order_by(Candidatura.match_score.desc()).all()
    h = '<h1>🏆 Ranking <span>// ' + v.titulo + '</span></h1>'
    h += '<p class="sub">Candidatos ordenados pelo Match Score — empresa ' + (v.empresa or '') + ' • ' + str(len(cands)) + ' candidaturas</p>'
    if not cands:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhuma candidatura nesta vaga ainda. <a class="link" href="/vagas/' + str(vid) + '">Ver vaga →</a></p></div>'
    else:
        medalhas = ['🥇', '🥈', '🥉']
        h += '<div class="painel"><table class="tabela"><thead><tr><th>Posição</th><th>Candidato</th><th>E-mail</th><th>Match</th><th>Entrevista</th><th>Etapa</th><th>Status</th><th>Chat</th></tr></thead><tbody>'
        for i, c in enumerate(cands):
            cand = Usuario.query.get(c.candidato_id)
            pos = i + 1
            medalha = medalhas[i] if i < 3 else '<span class="medalha">' + str(pos) + 'º</span>'
            cor_score = '#10b981' if c.match_score >= 80 else ('#f59e0b' if c.match_score >= 65 else '#ef4444')
            et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
            chat_link = '<a class="link" href="/conversa-iniciar?vaga=' + str(vid) + '&candidato=' + str(c.candidato_id) + '">💬</a>'
            ent = Entrevista.query.filter_by(vaga_id=vid, candidato_id=c.candidato_id).order_by(Entrevista.id.desc()).first()
            ent_html = '-'
            if ent:
                if ent.nota is not None:
                    ent_html = '<span class="pill realizada">⭐ ' + str(int(ent.nota)) + '/10</span>'
                else:
                    ent_html = '<span class="pill ' + ent.status + '">🎥 ' + ent.status + '</span>'
            h += ('<tr><td>' + medalha + '</td><td><b>' + (cand.nome if cand else '-') + '</b></td>'
                  '<td>' + (cand.email if cand else '-') + '</td>'
                  '<td><b style="color:' + cor_score + '">' + str(int(c.match_score)) + '%</b></td>'
                  '<td>' + ent_html + '</td>'
                  '<td><span class="pill ' + et + '">' + ETAPAS_INFO[et][0] + '</span></td>'
                  '<td><span class="pill ' + c.status + '">' + c.status + '</span></td>'
                  '<td>' + chat_link + '</td></tr>')
        h += '</tbody></table></div>'
        melhor = cands[0]
        cand_top = Usuario.query.get(melhor.candidato_id)
        if cand_top:
            h += '<div class="painel"><h4>⭐ Melhor Candidato</h4><p style="font-size:14px">'
            h += '<b>' + cand_top.nome + '</b> lidera com <b style="color:#22d3ee">' + str(int(melhor.match_score)) + '%</b> de compatibilidade.</p></div>'
    h += '<div class="status"><a class="btn cinza" href="/vagas/' + str(vid) + '">← Voltar para a vaga</a> '
    h += '<a class="btn cinza" href="/pipeline?vaga=' + str(vid) + '">📋 Ver Pipeline</a> '
    h += '<a class="btn cinza" href="/entrevistas?vaga=' + str(vid) + '">🎥 Entrevistas</a></div>'
    return pagina(h, '/vagas')

@app.route('/vagas/<int:vid>/candidatar')
def form_candidatura(vid):
    v = Vaga.query.get(vid)
    if not v:
        return pagina('<h1>Vaga não encontrada</h1>', '/vagas')
    u = usuario_atual()
    nome = u.nome if u else ''
    email = u.email if u else ''
    reqs = [r.skill for r in Requisito.query.filter_by(vaga_id=v.id).all()]
    req_html = ''
    if reqs:
        req_html = '<p class="sub">🎯 Requisitos: ' + ', '.join(reqs) + '</p>'
    h = '<h1>Candidatar-se <span>// ' + v.titulo + '</span></h1>'
    h += '<p class="sub">🏢 ' + (v.empresa or '-') + ' • Nível ' + (v.nivel_codigo or '-') + ' • ' + (v.regime or '-') + '</p>'
    h += req_html
    h += '<div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Seu nome</label><input id="nome" required value="' + nome + '" placeholder="Seu nome completo">'
    h += '<label>Seu e-mail</label><input id="email" type="email" required value="' + email + '" placeholder="voce@email.com">'
    h += '<label>Suas skills (separadas por vírgula)</label><input id="skills" placeholder="ex: python, sql, comunicação">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Enviar candidatura</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/vagas/' + str(vid) + '/candidatar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({nome:document.getElementById("nome").value,email:document.getElementById("email").value,'
          'skills:document.getElementById("skills").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){'
          'm.className="mensagem ok";m.innerHTML="✅ Candidatura enviada! Match Score: <b>"+res.j.match_score+"%</b> <a class=link href=/painel>Ver no painel →</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/vagas')

@app.route('/cadastrar-vaga')
@login_required
def pagina_cadastrar_vaga():
    u = usuario_atual()
    if not tem_permissao(u, 'cadastrar_vaga'):
        return redirect(url_for('painel'))
    h = '<h1>Publicar Vaga <span>// Nova oportunidade</span></h1><p class="sub">Publique uma vaga e o Agente Sourcing busca talentos automaticamente</p>'
    h += '<div class="painel" style="max-width:640px"><form id="f">'
    h += '<label>Título da vaga *</label><input id="titulo" required placeholder="ex: Desenvolvedor(a) Python Pleno">'
    h += '<label>Empresa *</label><select id="empresa" required><option value="">Selecione...</option>'
    for e in Empresa.query.all():
        h += '<option value="' + e.razao_social + '">' + e.razao_social + '</option>'
    h += '</select>'
    h += '<label>Nível (PCS) *</label><select id="nivel_codigo" required><option value="">Selecione...</option>'
    for n in Nivel.query.order_by(Nivel.ordem).all():
        h += '<option value="' + n.codigo + '">' + n.nome + ' (' + n.codigo + ')</option>'
    h += '</select>'
    h += '<label>Descrição</label><textarea id="descricao" rows="3" placeholder="Atividades, requisitos..."></textarea>'
    h += '<label>Requisitos / skills necessárias (separadas por vírgula)</label><input id="requisitos" placeholder="ex: python, flask, sql">'
    h += '<label>Regime</label><select id="regime"><option value="Remoto">Remoto</option><option value="Híbrido">Híbrido</option><option value="Presencial">Presencial</option></select>'
    h += '<label>Localização</label><input id="localizacao" placeholder="ex: Curitiba/PR">'
    h += '<label>Salário mínimo</label><input id="salario_min" type="number" placeholder="ex: 8000">'
    h += '<label>Salário máximo</label><input id="salario_max" type="number" placeholder="ex: 12000">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Publicar vaga</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'var d={titulo:document.getElementById("titulo").value,empresa:document.getElementById("empresa").value,'
          'nivel_codigo:document.getElementById("nivel_codigo").value,descricao:document.getElementById("descricao").value,'
          'requisitos:document.getElementById("requisitos").value,regime:document.getElementById("regime").value,'
          'localizacao:document.getElementById("localizacao").value,'
          'salario_min:document.getElementById("salario_min").value,salario_max:document.getElementById("salario_max").value};'
          'fetch("/api/vagas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Vaga publicada! <a class=link href=/vagas>Ver vagas</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/vagas')

@app.route('/cadastrar-empresa')
@login_required
def pagina_cadastrar_empresa():
    u = usuario_atual()
    if not tem_permissao(u, 'cadastrar_empresa'):
        return redirect(url_for('painel'))
    h = '<h1>Cadastrar Empresa <span>// Contratante</span></h1><p class="sub">Crie o perfil da sua organização no ecossistema</p>'
    h += '<div class="painel" style="max-width:640px"><form id="f">'
    h += '<label>Razão Social *</label><input id="razao_social" required placeholder="ex: RH Inovador S.A.">'
    h += '<label>Nome Fantasia</label><input id="nome_fantasia" placeholder="ex: RH Inovador">'
    h += '<label>CNPJ *</label><input id="cnpj" required placeholder="00.000.000/0001-00">'
    h += '<label>Porte</label><select id="porte"><option value="Pequeno">Pequeno</option><option value="Médio">Médio</option><option value="Grande">Grande</option></select>'
    h += '<label>Setor</label><input id="setor" placeholder="ex: Tecnologia">'
    h += '<label>E-mail de contato</label><input id="email" type="email" required placeholder="contato@empresa.com">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Cadastrar empresa</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'var d={razao_social:document.getElementById("razao_social").value,nome_fantasia:document.getElementById("nome_fantasia").value,'
          'cnpj:document.getElementById("cnpj").value,porte:document.getElementById("porte").value,'
          'setor:document.getElementById("setor").value,email:document.getElementById("email").value};'
          'fetch("/api/empresas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Empresa cadastrada!";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/empresas')

@app.route('/recrutamento')
def recrutamento():
    h = '<h1>Recrutamento Inteligente <span>// IA + Automação</span></h1>'
    h += '<p class="sub">Matching preditivo, triagem NLP e agentes autônomos trabalhando 24/7</p>'
    h += '<div class="painel"><h4>Indicadores ao Vivo</h4><div class="status">'
    h += '<div class="item"><span class="dot ciano"></span> Vagas ativas: <b>' + str(Vaga.query.filter_by(status='aberta').count()) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(Candidatura.query.count()) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> Candidatos: <b>' + str(Usuario.query.filter_by(tipo='candidato').count()) + '</b></div>'
    h += '<div class="item"><span class="dot ciano"></span> Entrevistas: <b>' + str(Entrevista.query.count()) + '</b></div>'
    h += '</div></div>'
    cards = [
        ('🧠', 'Matching Preditivo', 'IA compara skills, experiência e fit cultural para ranquear os melhores talentos.', '#3b82f6'),
        ('🔍', 'Triagem com NLP', 'Processa currículos, extrai skills implícitas e detecta viés automaticamente.', '#10b981'),
        ('✍️', 'Geração de Descrições', 'IA escreve descrições de vaga otimizadas para SEO e inclusão.', '#f59e0b'),
        ('🤖', 'Agente Sourcing', 'Busca candidatos em múltiplas fontes 24/7 assim que a vaga é publicada.', '#a855f7'),
        ('📅', 'Agente Scheduling', 'Negocia horários de entrevista automaticamente via chat.', '#22d3ee'),
        ('📩', 'Agente Follow-up', 'Mantém cada candidato informado durante todo o processo.', '#ef4444'),
    ]
    grade = ''
    for icone, titulo, desc, cor in cards:
        grade += ('<div class="card"><div class="icone" style="background:' + cor + '22">' + icone + '</div>'
                  '<h3>' + titulo + '</h3><p>' + desc + '</p><p style="margin-top:10px"><span class="pill aberta">● Ativo</span></p></div>')
    h += '<div class="grade">' + grade + '</div>'
    return pagina(h, '/recrutamento')

@app.route('/candidatos')
def candidatos():
    lista = Usuario.query.filter_by(tipo='candidato').all()
    u = usuario_atual()
    h = '<h1>Candidatos <span>// Talentos</span></h1>'
    h += '<p class="sub">' + str(len(lista)) + ' profissionais no ecossistema</p>'
    if u and u.tipo == 'admin':
        h += '<div class="painel"><p><a class="btn cinza" href="/cadastrar-candidato">👤➕ Cadastrar Candidato</a> <a class="btn cinza" href="/gerenciar">⚙️ Gerenciar</a></p></div>'
    h += '<div class="painel"><table class="tabela"><thead><tr><th>Nome</th><th>E-mail</th><th>Skills</th><th>Candidaturas</th><th>Status</th>' + ('<th>Ações</th>' if u and u.tipo == 'admin' else '') + '</tr></thead><tbody>'
    for cand in lista:
        p = Perfil.query.filter_by(usuario_id=cand.id).first()
        total = Candidatura.query.filter_by(candidato_id=cand.id).count()
        skills = (p.skills[:60] + '...') if p and p.skills and len(p.skills) > 60 else (p.skills if p else '-')
        acoes = ('<a class="btn cinza" href="/editar-candidato/' + str(cand.id) + '">✏️ Editar</a>') if u and u.tipo == 'admin' else ''
        h += ('<tr><td><b>' + cand.nome + '</b></td><td>' + cand.email + '</td><td>' + (skills or '-') + '</td>'
              '<td>' + str(total) + '</td>'
              '<td><span class="pill ' + ('candidato' if cand.ativo else 'fechada') + '">' + ('Ativo' if cand.ativo else 'Inativo') + '</span></td>'
              + ('<td>' + acoes + '</td>' if u and u.tipo == 'admin' else '') + '</tr>')
    h += '</tbody></table></div>'
    return pagina(h, '/candidatos')

@app.route('/empresas')
def empresas():
    lista = Usuario.query.filter_by(tipo='empresa').all()
    u = usuario_atual()
    h = '<h1>Empresas <span>// Contratantes</span></h1>'
    h += '<p class="sub">' + str(len(lista)) + ' organizações no ecossistema</p>'
    if u and tem_permissao(u, 'cadastrar_empresa'):
        h += '<div class="painel"><p><a class="btn cinza" href="/cadastrar-empresa">➕ Cadastrar Empresa</a></p></div>'
    h += '<div class="painel"><table class="tabela"><thead><tr><th>Razão Social</th><th>E-mail</th><th>Setor</th><th>Status</th></tr></thead><tbody>'
    for usr in lista:
        emp = Empresa.query.filter_by(usuario_id=usr.id).first()
        h += ('<tr><td><b>' + usr.nome + '</b></td><td>' + usr.email + '</td><td>' + (emp.setor if emp else '-') + '</td>'
              '<td><span class="pill aberta">Verificada</span></td></tr>')
    h += '</tbody></table></div>'
    return pagina(h, '/empresas')

@app.route('/analytics')
def analytics():
    total_vagas = Vaga.query.count()
    total_candidaturas = Candidatura.query.count()
    total_candidatos = Usuario.query.filter_by(tipo='candidato').count()
    total_empresas = Usuario.query.filter_by(tipo='empresa').count()
    total_conversas = Conversa.query.count()
    total_entrevistas = Entrevista.query.count()
    realizadas = Entrevista.query.filter_by(status='realizada').count()
    scores = [c.match_score or 0 for c in Candidatura.query.all()]
    score_medio = round(sum(scores) / len(scores), 1) if scores else 0
    taxa_conversao = round(realizadas / total_candidaturas * 100, 1) if total_candidaturas else 0
    h = '<h1>Analytics <span>// People Analytics</span></h1>'
    h += '<p class="sub">KPIs e dashboards em tempo real do ecossistema</p>'
    h += '<div class="painel"><h4>KPIs Principais</h4><div class="status">'
    h += '<div class="item"><span class="dot ciano"></span> Vagas: <b>' + str(total_vagas) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(total_candidaturas) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> Candidatos: <b>' + str(total_candidatos) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Empresas: <b>' + str(total_empresas) + '</b></div>'
    h += '<div class="item"><span class="dot ciano"></span> Conversas: <b>' + str(total_conversas) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> Entrevistas: <b>' + str(total_entrevistas) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Taxa conversão: <b>' + str(taxa_conversao) + '%</b></div>'
    h += '<div class="item"><span class="dot"></span> Match médio: <b>' + str(score_medio) + '%</b></div>'
    h += '</div></div>'
    por_nivel = {}
    for v in Vaga.query.all():
        cod = v.nivel_codigo or 'Geral'
        por_nivel[cod] = por_nivel.get(cod, 0) + 1
    itens = sorted(por_nivel.items(), key=lambda x: x[1], reverse=True)[:8]
    max_v = max([c for _, c in itens], default=1) or 1
    h += '<div class="painel"><h4>Vagas por Nível</h4>'
    for cod, qtd in itens:
        pct = int(qtd / max_v * 100)
        h += '<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:13px"><span>' + cod + '</span><b>' + str(qtd) + '</b></div>'
        h += '<div style="background:rgba(10,22,40,.8);border-radius:6px;height:10px;margin-top:4px"><div style="background:linear-gradient(90deg,#1d4ed8,#22d3ee);width:' + str(pct) + '%;height:10px;border-radius:6px"></div></div></div>'
    h += '</div>'
    por_etapa = {}
    for c in Candidatura.query.all():
        et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
        por_etapa[et] = por_etapa.get(et, 0) + 1
    if por_etapa:
        h += '<div class="painel"><h4>Distribuição por Etapa (Pipeline)</h4>'
        for et in ETAPAS:
            qtd = por_etapa.get(et, 0)
            if qtd:
                nome_et, cor = ETAPAS_INFO[et]
                h += '<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:13px"><span style="color:' + cor + '">●</span> <span>' + nome_et + '</span><b>' + str(qtd) + '</b></div>'
                h += '<div style="background:rgba(10,22,40,.8);border-radius:6px;height:10px;margin-top:4px"><div style="background:' + cor + ';width:' + str(min(100, int(qtd / max(1, max(por_etapa.values())) * 100))) + '%;height:10px;border-radius:6px"></div></div></div>'
        h += '</div>'
    ent_status = {}
    for e in Entrevista.query.all():
        ent_status[e.status] = ent_status.get(e.status, 0) + 1
    if ent_status:
        h += '<div class="painel"><h4>Entrevistas por Status</h4>'
        for st, qtd in ent_status.items():
            cor = {'agendada': '#f59e0b', 'confirmada': '#22d3ee', 'realizada': '#10b981', 'cancelada': '#ef4444'}.get(st, '#8fa3c0')
            h += '<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:13px"><span style="color:' + cor + '">●</span> <span>' + st + '</span><b>' + str(qtd) + '</b></div></div>'
        h += '</div>'
    ultimas = Candidatura.query.order_by(Candidatura.id.desc()).limit(10).all()
    if ultimas:
        h += '<div class="painel"><h4>Últimas Candidaturas</h4><table class="tabela"><thead><tr><th>Vaga</th><th>Candidato</th><th>Match</th><th>Etapa</th><th>Status</th></tr></thead><tbody>'
        for c in ultimas:
            v = Vaga.query.get(c.vaga_id)
            usr = Usuario.query.get(c.candidato_id)
            et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
            h += ('<tr><td>' + (v.titulo if v else '-') + '</td><td>' + (usr.nome if usr else '-') + '</td>'
                  '<td><b style="color:#22d3ee">' + str(int(c.match_score or 0)) + '%</b></td>'
                  '<td><span class="pill ' + et + '">' + ETAPAS_INFO[et][0] + '</span></td>'
                  '<td><span class="pill ' + c.status + '">' + c.status + '</span></td></tr>')
        h += '</tbody></table></div>'
    return pagina(h, '/analytics')

@app.route('/conectividade')
def conectividade():
    h = '<h1>Conectividade <span>// Comunicação Unificada</span></h1>'
    h += '<p class="sub">Videoconferência, WhatsApp Business, e-mail corporativo, chat e notificações</p>'
    mods = [
        ('🎥', 'Videoconferência', 'Salas com até 5 participantes. WebRTC + Jitsi. Transcrição com IA.'),
        ('💬', 'WhatsApp Business', 'Chatbot de triagem, templates de convite, lembretes automáticos.'),
        ('📧', 'E-mail Corporativo', 'Templates para todo o ciclo: candidatura → oferta → onboarding.'),
        ('💭', 'Chat em Tempo Real', 'Mensagens instantâneas entre candidato e empresa por vaga. Disponível em 💬 Mensagens.'),
        ('🔔', 'Notificações Push', 'Multicanal: push, e-mail, WhatsApp. Preferências por usuário.'),
        ('📅', 'Agenda Inteligente', 'Sugestão de horários, detecção de fuso, lembretes 24h/1h.'),
    ]
    grade = ''
    for icone, titulo, desc in mods:
        grade += '<div class="card"><div class="icone" style="background:#22d3ee22">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p><p style="margin-top:10px"><span class="pill aberta">Integrado</span></p></div>'
    h += '<div class="grade">' + grade + '</div>'
    h += '<div class="painel"><h4>Agentes de Comunicação</h4><div class="status">'
    h += '<div class="item"><span class="dot ciano"></span> Agente Convite</div>'
    h += '<div class="item"><span class="dot"></span> Agente Lembrete</div>'
    h += '<div class="item"><span class="dot roxo"></span> Agente Feedback</div>'
    h += '<div class="item"><span class="dot"></span> Agente Onboarding</div>'
    h += '<div class="item"><span class="dot ciano"></span> Agente Pesquisa</div>'
    h += '</div></div>'
    return pagina(h, '/conectividade')

@app.route('/experiencia')
def experiencia():
    h = '<h1>Experiência <span>// Jornada do Talento</span></h1>'
    h += '<p class="sub">Onboarding digital, mentoria com IA, feedback contínuo e comunidade</p>'
    mods = [
        ('🚀', 'Onboarding Digital', 'Jornada guiada para novos candidatos e empresas com gamificação.'),
        ('🎓', 'Mentoria com IA', 'Matching mentor-mentorado e assistente de carreira 24/7.'),
        ('💬', 'Feedback Loop', 'Feedback bidirecional obrigatório com transparência total.'),
        ('🗺️', 'Plano de Carreira', 'Roadmap personalizado com marcos, prazos e comparação de mercado.'),
        ('🤝', 'Comunidade', 'Fóruns, eventos e networking inteligente por objetivos.'),
        ('🏅', 'Reconhecimento', 'Badges e gamificação por conquistas e desenvolvimento.'),
    ]
    grade = ''
    for icone, titulo, desc in mods:
        grade += '<div class="card"><div class="icone" style="background:#14b8a622">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p></div>'
    h += '<div class="grade">' + grade + '</div>'
    return pagina(h, '/experiencia')

@app.route('/inovacao')
def inovacao():
    h = '<h1>Inovação <span>// Futuro do Trabalho</span></h1>'
    h += '<p class="sub">Web3, blockchain, Skills DNA, realidade virtual e recrutamento assíncrono</p>'
    mods = [
        ('⛓️', 'Credenciais Blockchain', 'Diplomas e certificações verificados como NFTs soulbound.'),
        ('🧬', 'Skills DNA', 'Mapeamento genético de habilidades para carreira precisa.'),
        ('🥽', 'VR para Entrevistas', 'Salas virtuais, visitas ao escritório e assessments imersivos.'),
        ('📜', 'Recrutamento Assíncrono', 'Processos seletivos sem horário fixo, com desafios práticos.'),
        ('🤖', 'Retenção Preditiva', 'IA identifica risco de desligamento com até 6 meses de antecedência.'),
        ('🌐', 'Web3 & DAOs', 'Governança descentralizada e wallets para talentos.'),
    ]
    grade = ''
    for icone, titulo, desc in mods:
        grade += '<div class="card"><div class="icone" style="background:#8b5cf622">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p></div>'
    h += '<div class="grade">' + grade + '</div>'
    return pagina(h, '/inovacao')

# ================= MATCH SCORE INTELIGENTE =================
def calcular_match(vaga, candidato):
    reqs = [r.skill.lower().strip() for r in Requisito.query.filter_by(vaga_id=vaga.id).all()]
    perfil = Perfil.query.filter_by(usuario_id=candidato.id).first()
    skills = [s.lower().strip() for s in (perfil.skills or '').split(',') if s.strip()] if perfil else []
    if reqs and skills:
        hits = 0
        for r in reqs:
            for sk in skills:
                if r in sk or sk in r:
                    hits += 1
                    break
        base = int(50 + (hits / len(reqs)) * 40)
        return min(98, base + random.randint(0, 5))
    return random.randint(62, 97)

# ================= API JSON =================
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'online', 'versao': '10.0.0',
        'conexoes_ativas': conexoes_ativas, 'conexoes_maximas': MAX_CONEXOES,
        'modulos': ['usuarios', 'vagas', 'candidatos', 'empresas', 'pcs', 'conectividade',
                    'recrutamento', 'analytics', 'experiencia', 'inovacao', 'pipeline', 'mensagens',
                    'entrevistas', 'gerenciamento'],
        'agentes': ['sourcing', 'triagem', 'scheduling', 'followup', 'dei'],
        'trilhas': Trilha.query.count(), 'niveis': Nivel.query.count(), 'vagas': Vaga.query.count(),
        'candidaturas': Candidatura.query.count(), 'conversas': Conversa.query.count(),
        'mensagens': Mensagem.query.count(), 'entrevistas': Entrevista.query.count(),
    })

@app.route('/api/trilhas')
def api_trilhas():
    return jsonify([{'id': t.id, 'nome': t.nome, 'descricao': t.descricao} for t in Trilha.query.all()])

@app.route('/api/niveis')
def api_niveis():
    return jsonify([{'id': n.id, 'codigo': n.codigo, 'nome': n.nome, 'ordem': n.ordem,
                     'salario_min': n.salario_min, 'salario_max': n.salario_max,
                     'autonomia': n.autonomia, 'impacto': n.impacto, 'trilha_id': n.trilha_id}
                    for n in Nivel.query.order_by(Nivel.ordem).all()])

@app.route('/api/vagas')
def api_vagas():
    return jsonify([{'id': v.id, 'titulo': v.titulo, 'empresa': v.empresa,
                     'nivel_codigo': v.nivel_codigo, 'status': v.status,
                     'regime': v.regime, 'localizacao': v.localizacao,
                     'requisitos': [r.skill for r in Requisito.query.filter_by(vaga_id=v.id).all()]}
                    for v in Vaga.query.all()])

@app.route('/api/registro', methods=['POST'])
def api_registro():
    d = request.get_json(force=True)
    nome = (d.get('nome') or '').strip()
    email = (d.get('email') or '').strip()
    senha = d.get('senha') or ''
    tipo = d.get('tipo') or 'candidato'
    if not nome or not email or not senha:
        return jsonify({'erro': 'Preencha nome, email e senha'}), 400
    if len(senha) < 6:
        return jsonify({'erro': 'Senha deve ter pelo menos 6 caracteres'}), 400
    if Usuario.query.filter_by(email=email).first():
        return jsonify({'erro': 'Email já cadastrado'}), 409
    u = Usuario(nome=nome, email=email, senha_hash=generate_password_hash(senha), tipo=tipo, ativo=True)
    db.session.add(u)
    db.session.commit()
    if tipo == 'empresa':
        db.session.add(Empresa(usuario_id=u.id, razao_social=nome, nome_fantasia=nome))
        db.session.commit()
    session['user_id'] = u.id
    return jsonify({'ok': True, 'msg': 'Conta criada com sucesso',
                    'usuario': {'id': u.id, 'nome': u.nome, 'email': u.email, 'tipo': u.tipo}}), 201

@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.get_json(force=True)
    u = Usuario.query.filter_by(email=(d.get('email') or '').strip()).first()
    if not u or not check_password_hash(u.senha_hash, d.get('senha') or ''):
        return jsonify({'erro': 'Credenciais inválidas'}), 401
    if not u.ativo:
        return jsonify({'erro': 'Conta desativada. Fale com o administrador.'}), 403
    session['user_id'] = u.id
    return jsonify({'ok': True, 'msg': 'Bem-vindo(a)!',
                    'usuario': {'id': u.id, 'nome': u.nome, 'email': u.email, 'tipo': u.tipo}})

@app.route('/api/perfil', methods=['POST'])
def api_perfil():
    u = usuario_atual()
    if not u:
        return jsonify({'erro': 'Faça login'}), 401
    d = request.get_json(force=True)
    p = Perfil.query.filter_by(usuario_id=u.id).first()
    if not p:
        p = Perfil(usuario_id=u.id)
        db.session.add(p)
    p.skills = (d.get('skills') or '').strip()
    p.resumo = (d.get('resumo') or '').strip()
    p.linkedin = (d.get('linkedin') or '').strip()
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Perfil salvo'})

@app.route('/api/importar-plano', methods=['POST'])
def api_importar_plano():
    u = usuario_atual()
    if not u or not tem_permissao(u, 'importar_plano'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    texto = (d.get('texto') or '').strip()
    if not texto:
        return jsonify({'erro': 'Cole o conteúdo do plano primeiro'}), 400
    importados = 0
    trilhas_criadas = 0
    atualizados = 0
    erros = []
    for raw in texto.splitlines():
        linha = raw.strip()
        if not linha:
            continue
        normalizada = linha.replace('\t', ';').replace('|', ';')
        if normalizada.lower().startswith('trilha'):
            continue
        partes = [p.strip() for p in normalizada.split(';')]
        partes = [p for p in partes if p]
        if len(partes) < 3:
            erros.append('Linha ignorada (faltam colunas): ' + linha[:60])
            continue
        trilha_nome = partes[0]
        codigo = partes[1].upper()
        nome_nivel = partes[2]
        smin = parse_float(partes[3]) if len(partes) > 3 else None
        smax = parse_float(partes[4]) if len(partes) > 4 else None
        autonomia = partes[5] if len(partes) > 5 else None
        impacto = partes[6] if len(partes) > 6 else None
        t = Trilha.query.filter(Trilha.nome.ilike(trilha_nome)).first()
        if not t:
            t = Trilha(nome=trilha_nome, descricao='Importada do plano')
            db.session.add(t)
            db.session.flush()
            trilhas_criadas += 1
        n = Nivel.query.filter_by(trilha_id=t.id, codigo=codigo).first()
        if n:
            n.nome = nome_nivel
            n.salario_min = smin if smin is not None else n.salario_min
            n.salario_max = smax if smax is not None else n.salario_max
            n.autonomia = autonomia or n.autonomia
            n.impacto = impacto or n.impacto
            atualizados += 1
        else:
            max_ordem = db.session.query(db.func.max(Nivel.ordem)).filter_by(trilha_id=t.id).scalar() or 0
            db.session.add(Nivel(trilha_id=t.id, codigo=codigo, nome=nome_nivel,
                                 ordem=max_ordem + 1, salario_min=smin, salario_max=smax,
                                 autonomia=autonomia, impacto=impacto))
            importados += 1
    db.session.commit()
    msg = 'Importação concluída! Novos níveis: ' + str(importados) + ' • Atualizados: ' + str(atualizados) + ' • Trilhas criadas: ' + str(trilhas_criadas)
    if erros:
        msg += ' • Avisos: ' + str(len(erros))
    return jsonify({'ok': True, 'msg': msg, 'importados': importados,
                    'atualizados': atualizados, 'trilhas_criadas': trilhas_criadas,
                    'erros': erros[:5]})

@app.route('/api/vagas/cadastrar', methods=['POST'])
def api_cadastrar_vaga():
    u = usuario_atual()
    if not u or not tem_permissao(u, 'cadastrar_vaga'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    titulo = (d.get('titulo') or '').strip()
    empresa = (d.get('empresa') or '').strip()
    nivel = (d.get('nivel_codigo') or '').strip()
    if not titulo or not empresa or not nivel:
        return jsonify({'erro': 'Preencha título, empresa e nível'}), 400
    v = Vaga(titulo=titulo, descricao=d.get('descricao'), empresa=empresa, nivel_codigo=nivel,
             status='aberta', salario_min=parse_float(d.get('salario_min')),
             salario_max=parse_float(d.get('salario_max')), regime=d.get('regime'),
             localizacao=d.get('localizacao'))
    db.session.add(v)
    db.session.flush()
    reqs = (d.get('requisitos') or '').strip()
    if reqs:
        for r in [x.strip() for x in reqs.split(',') if x.strip()]:
            db.session.add(Requisito(vaga_id=v.id, skill=r))
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Vaga publicada com sucesso', 'vaga_id': v.id})

@app.route('/api/empresas/cadastrar', methods=['POST'])
def api_cadastrar_empresa():
    u = usuario_atual()
    if not u or not tem_permissao(u, 'cadastrar_empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    razao = (d.get('razao_social') or '').strip()
    cnpj = (d.get('cnpj') or '').strip()
    email = (d.get('email') or '').strip()
    if not razao or not cnpj or not email:
        return jsonify({'erro': 'Preencha razão social, CNPJ e e-mail'}), 400
    usr = Usuario.query.filter_by(email=email).first()
    if not usr:
        usr = Usuario(nome=razao, email=email, senha_hash=generate_password_hash('empresa123'),
                      tipo='empresa', ativo=True)
        db.session.add(usr)
        db.session.flush()
    emp = Empresa(usuario_id=usr.id, razao_social=razao, nome_fantasia=d.get('nome_fantasia'),
                  cnpj=cnpj, porte=d.get('porte'), setor=d.get('setor'),
                  descricao=d.get('descricao'), cultura=d.get('cultura'))
    db.session.add(emp)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Empresa cadastrada com sucesso', 'empresa_id': emp.id})

@app.route('/api/admin/cadastrar-candidato', methods=['POST'])
def api_admin_cadastrar_candidato():
    u = usuario_atual()
    if not u or u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito ao administrador'}), 403
    d = request.get_json(force=True)
    nome = (d.get('nome') or '').strip()
    email = (d.get('email') or '').strip()
    senha = d.get('senha') or ''
    if not nome or not email or not senha:
        return jsonify({'erro': 'Preencha nome, e-mail e senha'}), 400
    if len(senha) < 6:
        return jsonify({'erro': 'Senha deve ter pelo menos 6 caracteres'}), 400
    if Usuario.query.filter_by(email=email).first():
        return jsonify({'erro': 'E-mail já cadastrado'}), 409
    novo = Usuario(nome=nome, email=email, senha_hash=generate_password_hash(senha),
                   tipo='candidato', ativo=True)
    db.session.add(novo)
    db.session.flush()
    skills = (d.get('skills') or '').strip()
    resumo = (d.get('resumo') or '').strip()
    if skills or resumo:
        db.session.add(Perfil(usuario_id=novo.id, skills=skills or None, resumo=resumo or None))
    for mod in MODULOS_GERENCIAVEIS:
        db.session.add(Permissao(usuario_id=novo.id, modulo=mod,
                                 habilitado=mod in PERMISSOES_PADRAO.get('candidato', [])))
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidato cadastrado com sucesso',
                    'candidato': {'id': novo.id, 'nome': novo.nome, 'email': novo.email}}), 201

@app.route('/api/admin/editar-candidato', methods=['POST'])
def api_admin_editar_candidato():
    u = usuario_atual()
    if not u or u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito ao administrador'}), 403
    d = request.get_json(force=True)
    cand = Usuario.query.get(d.get('usuario_id', type=int))
    if not cand or cand.tipo != 'candidato':
        return jsonify({'erro': 'Candidato não encontrado'}), 404
    nome = (d.get('nome') or '').strip()
    email = (d.get('email') or '').strip()
    if not nome or not email:
        return jsonify({'erro': 'Preencha nome e e-mail'}), 400
    outro = Usuario.query.filter(Usuario.email == email, Usuario.id != cand.id).first()
    if outro:
        return jsonify({'erro': 'E-mail já usado por outro usuário'}), 409
    cand.nome = nome
    cand.email = email
    senha = d.get('senha') or ''
    if senha:
        if len(senha) < 6:
            return jsonify({'erro': 'Senha deve ter pelo menos 6 caracteres'}), 400
        cand.senha_hash = generate_password_hash(senha)
    cand.ativo = bool(d.get('ativo', True))
    p = Perfil.query.filter_by(usuario_id=cand.id).first()
    if not p:
        p = Perfil(usuario_id=cand.id)
        db.session.add(p)
    p.skills = (d.get('skills') or '').strip()
    p.resumo = (d.get('resumo') or '').strip()
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidato atualizado com sucesso'})

@app.route('/api/admin/agendar-entrevista', methods=['POST'])
def api_admin_agendar_entrevista():
    u = usuario_atual()
    if not u or u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito ao administrador'}), 403
    d = request.get_json(force=True)
    cand = Usuario.query.get(d.get('candidato_id', type=int))
    v = Vaga.query.get(d.get('vaga_id', type=int))
    if not cand or cand.tipo != 'candidato' or not v:
        return jsonify({'erro': 'Candidato ou vaga inválidos'}), 400
    data = (d.get('data') or '').strip()
    hora = (d.get('hora') or '').strip()
    try:
        data_hora = datetime.strptime(data + ' ' + hora, '%Y-%m-%d %H:%M')
    except Exception:
        return jsonify({'erro': 'Data/hora inválidas'}), 400
    emp = usuario_empresa_da_vaga(v)
    if not emp:
        emp = u
    c = Candidatura.query.filter_by(vaga_id=v.id, candidato_id=cand.id).first()
    if not c:
        c = Candidatura(vaga_id=v.id, candidato_id=cand.id, match_score=calcular_match(v, cand),
                        status='pendente', etapa='triagem')
        db.session.add(c)
        db.session.flush()
    c.etapa = 'entrevista'
    ent = Entrevista(vaga_id=v.id, candidato_id=cand.id, empresa_id=emp.id, data_hora=data_hora,
                     tipo=(d.get('tipo') or 'Video'), link=(d.get('link') or '').strip(), status='agendada')
    db.session.add(ent)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Entrevista agendada!'})

@app.route('/api/admin/permissoes', methods=['POST'])
def api_admin_permissoes():
    u = usuario_atual()
    if not u or u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito ao administrador'}), 403
    d = request.get_json(force=True)
    alvo = Usuario.query.get(d.get('usuario_id', type=int))
    if not alvo or alvo.tipo == 'admin':
        return jsonify({'erro': 'Usuário inválido'}), 400
    perms = d.get('permissoes') or {}
    if '_ativo' in perms:
        alvo.ativo = bool(perms['_ativo'])
        perms.pop('_ativo', None)
    for mod in MODULOS_GERENCIAVEIS:
        p = Permissao.query.filter_by(usuario_id=alvo.id, modulo=mod).first()
        if not p:
            p = Permissao(usuario_id=alvo.id, modulo=mod)
            db.session.add(p)
        if mod in perms:
            p.habilitado = bool(perms[mod])
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Permissões salvas!'})

@app.route('/api/pipeline/<int:cid>/etapa', methods=['POST'])
def pipeline_etapa(cid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    c = Candidatura.query.get(cid)
    if not c:
        return jsonify({'erro': 'Candidatura não encontrada'}), 404
    d = request.get_json(force=True)
    etapa = (d.get('etapa') or '').strip()
    if etapa not in ETAPAS:
        return jsonify({'erro': 'Etapa inválida'}), 400
    c.etapa = etapa
    db.session.execute(text("UPDATE candidatura SET etapa_atualizada_em = :t WHERE id = :i"), {'t': datetime.utcnow(), 'i': c.id})
    if etapa == 'contratado':
        c.status = 'aprovado'
    elif etapa == 'rejeitado':
        c.status = 'rejeitado'
    elif c.status in ('aprovado', 'rejeitado'):
        c.status = 'pendente'
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidato movido para ' + ETAPAS_INFO[etapa][0], 'etapa': etapa})

@app.route('/api/entrevistas/cadastrar', methods=['POST'])
def api_cadastrar_entrevista():
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    c = Candidatura.query.get(d.get('candidatura', type=int) or 0)
    if not c:
        return jsonify({'erro': 'Candidatura não encontrada'}), 404
    data = (d.get('data') or '').strip()
    hora = (d.get('hora') or '').strip()
    try:
        data_hora = datetime.strptime(data + ' ' + hora, '%Y-%m-%d %H:%M')
    except Exception:
        return jsonify({'erro': 'Data/hora inválidas'}), 400
    emp = u if u.tipo == 'empresa' else (usuario_empresa_da_vaga(Vaga.query.get(c.vaga_id)) or u)
    ent = Entrevista(vaga_id=c.vaga_id, candidato_id=c.candidato_id, empresa_id=emp.id,
                     data_hora=data_hora, tipo=(d.get('tipo') or 'Video'),
                     link=(d.get('link') or '').strip(), status='agendada')
    db.session.add(ent)
    if c.etapa == 'triagem':
        c.etapa = 'entrevista'
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Entrevista agendada!', 'entrevista_id': ent.id})

@app.route('/api/entrevistas/<int:eid>/status')
def api_entrevista_status(eid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    e = Entrevista.query.get(eid)
    if not e:
        return jsonify({'erro': 'Entrevista não encontrada'}), 404
    novo = request.args.get('novo', '')
    if novo not in ('agendada', 'confirmada', 'realizada', 'cancelada'):
        return jsonify({'erro': 'Status inválido'}), 400
    e.status = novo
    if novo == 'cancelada':
        c = Candidatura.query.filter_by(vaga_id=e.vaga_id, candidato_id=e.candidato_id).first()
        if c and c.etapa == 'entrevista':
            c.etapa = 'triagem'
    db.session.commit()
    return redirect(url_for('entrevistas', vaga=e.vaga_id))

@app.route('/api/entrevistas/<int:eid>/avaliar', methods=['POST'])
def api_avaliar_entrevista(eid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    e = Entrevista.query.get(eid)
    if not e:
        return jsonify({'erro': 'Entrevista não encontrada'}), 404
    d = request.get_json(force=True)
    try:
        nota = float(d.get('nota'))
        if nota < 0 or nota > 10:
            raise ValueError
    except Exception:
        return jsonify({'erro': 'Nota deve ser entre 0 e 10'}), 400
    e.nota = nota
    e.comentario = (d.get('comentario') or '').strip()
    if e.status != 'realizada':
        e.status = 'realizada'
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Avaliação salva!', 'nota': nota})

@app.route('/api/conversas/<int:cid>/mensagens', methods=['GET', 'POST'])
def api_mensagens(cid):
    u = usuario_atual()
    if not u:
        return jsonify({'erro': 'Faça login'}), 401
    c = Conversa.query.get(cid)
    if not c:
        return jsonify({'erro': 'Conversa não encontrada'}), 404
    if u.id not in (c.candidato_id, c.empresa_id) and u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito'}), 403
    if request.method == 'POST':
        d = request.get_json(force=True)
        texto = (d.get('texto') or '').strip()
        if not texto:
            return jsonify({'erro': 'Mensagem vazia'}), 400
        m = Mensagem(conversa_id=cid, remetente_id=u.id, texto=texto, lida=False)
        db.session.add(m)
        db.session.commit()
        return jsonify({'ok': True, 'msg': 'Enviada'})
    msgs = Mensagem.query.filter_by(conversa_id=cid).order_by(Mensagem.id).all()
    return jsonify({'ok': True, 'mensagens': [
        {'id': m.id, 'texto': m.texto, 'remetente_id': m.remetente_id,
         'autor': (Usuario.query.get(m.remetente_id).nome.split()[0] if Usuario.query.get(m.remetente_id) else ''),
         'hora': m.criada_em.strftime('%H:%M') if m.criada_em else ''}
        for m in msgs]})

@app.route('/api/vagas/<int:vid>/candidatar', methods=['POST'])
def candidatar(vid):
    v = Vaga.query.get(vid)
    if not v:
        return jsonify({'erro': 'Vaga não encontrada'}), 404
    d = request.get_json(force=True)
    nome = (d.get('nome') or '').strip()
    email = (d.get('email') or '').strip()
    skills_informadas = (d.get('skills') or '').strip()
    if not nome or not email:
        return jsonify({'erro': 'Preencha nome e e-mail'}), 400
    cand = Usuario.query.filter_by(email=email).first()
    if not cand:
        cand = Usuario(nome=nome, email=email, senha_hash=generate_password_hash('candidato123'),
                       tipo='candidato', ativo=True)
        db.session.add(cand)
        db.session.flush()
        for mod in MODULOS_GERENCIAVEIS:
            db.session.add(Permissao(usuario_id=cand.id, modulo=mod,
                                     habilitado=mod in PERMISSOES_PADRAO.get('candidato', [])))
    else:
        cand.nome = nome
    if skills_informadas:
        p = Perfil.query.filter_by(usuario_id=cand.id).first()
        if not p:
            p = Perfil(usuario_id=cand.id)
            db.session.add(p)
        p.skills = skills_informadas
    ja = Candidatura.query.filter_by(vaga_id=vid, candidato_id=cand.id).first()
    if ja:
        return jsonify({'ok': True, 'msg': 'Você já está candidato a esta vaga',
                        'vaga': v.titulo, 'candidato': cand.nome, 'match_score': int(ja.match_score),
                        'status': ja.status, 'etapa': ja.etapa})
    score = calcular_match(v, cand)
    c = Candidatura(vaga_id=vid, candidato_id=cand.id, match_score=score, status='pendente', etapa='triagem')
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidatura enviada', 'vaga': v.titulo, 'empresa': v.empresa,
                    'candidato': cand.nome, 'email': email, 'match_score': score, 'status': 'pendente',
                    'etapa': 'triagem'})
from sqlalchemy import text

# ================= V10: ETAPAS, TESTES, MONITORAMENTO E FINANCEIRO =================

TIPO_FINANCA = {
    'custo_vaga': '💰 Custo da Vaga',
    'comissao_analista': '🧑‍💼 Comissão Analista',
    'comissao_rh': '🤝 Comissão RH',
    'receita': '📈 Receita do Cliente',
    'outro': '📦 Outro',
}

class ConfigEtapa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    nome = db.Column(db.String(80), nullable=False)
    ordem = db.Column(db.Integer, default=1)
    sla_dias = db.Column(db.Integer, default=3)
    tem_teste = db.Column(db.Boolean, default=False)
    atividades = db.Column(db.Text)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

class Teste(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    etapa_nome = db.Column(db.String(80))
    nome = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(30), default='tecnico')
    nota_max = db.Column(db.Float, default=10.0)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

class ResultadoTeste(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teste_id = db.Column(db.Integer, db.ForeignKey('teste.id'))
    candidato_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    nota = db.Column(db.Float)
    status = db.Column(db.String(20), default='pendente')
    observacao = db.Column(db.Text)
    realizado_em = db.Column(db.DateTime)

class Financa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    tipo = db.Column(db.String(30), default='custo_vaga')
    descricao = db.Column(db.String(200))
    valor = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pendente')
    nota_fiscal = db.Column(db.String(30))
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)
    paga_em = db.Column(db.DateTime)

MAPA_ETAPA_KANBAN = {'triagem': 'triagem', 'entrevista': 'entrevista', 'proposta': 'proposta', 'contratado': 'contratado', 'rejeitado': 'rejeitado'}

def criar_etapas_padrao(vaga_id):
    if ConfigEtapa.query.filter_by(vaga_id=vaga_id).first():
        return
    padrao = [
        ('Triagem', 1, 3, False, 'Análise de currículo, perfil e fit inicial.'),
        ('Testes', 2, 5, True, 'Aplicação de testes técnicos/comportamentais.'),
        ('Entrevista', 3, 7, False, 'Entrevista com RH e gestor da área.'),
        ('Proposta', 4, 5, False, 'Negociação, aprovação e envio da proposta.'),
    ]
    for nome, ordem, sla, teste, atv in padrao:
        db.session.add(ConfigEtapa(vaga_id=vaga_id, nome=nome, ordem=ordem, sla_dias=sla, tem_teste=teste, atividades=atv))
    db.session.commit()

def achar_config_etapa(vaga_id, etapa_kanban):
    nome_kanban = MAPA_ETAPA_KANBAN.get(etapa_kanban, etapa_kanban or '')
    for ce in ConfigEtapa.query.filter_by(vaga_id=vaga_id).all():
        if ce.nome and nome_kanban and (nome_kanban in ce.nome.lower() or ce.nome.lower() in nome_kanban):
            return ce
    return None

def get_etapa_atualizada(cid):
    try:
        r = db.session.execute(text("SELECT etapa_atualizada_em FROM candidatura WHERE id=:i"), {'i': cid}).fetchone()
        if r and r[0]:
            return r[0]
    except Exception:
        pass
    return None

def dias_na_etapa(c):
    ref = get_etapa_atualizada(c.id) or c.criada_em
    if not ref:
        return 0
    return (datetime.utcnow() - ref).days

# ================= V10: CONFIG DE ETAPAS =================
@app.route('/config-etapas')
@gestor_required
def config_etapas():
    vaga_id = request.args.get('vaga', type=int)
    vagas = Vaga.query.order_by(Vaga.id.desc()).all()
    v = Vaga.query.get(vaga_id) if vaga_id else (vagas[0] if vagas else None)
    if not v:
        return pagina('<h1>Nenhuma vaga cadastrada</h1>', '/')
    h = '<h1>🧪 Etapas e Testes <span>// ' + v.titulo + '</span></h1>'
    h += '<p class="sub">Padronize as etapas da vaga, defina prazos (SLA), atividades e testes de cada fase.</p>'
    h += '<div class="caixa-busca"><select onchange="location.href=\'/config-etapas?vaga=\'+this.value">'
    for vg in vagas:
        sel = ' selected' if vg.id == v.id else ''
        h += '<option value="' + str(vg.id) + '"' + sel + '>💼 ' + vg.titulo + '</option>'
    h += '</select><a class="btn cinza" href="/testes?vaga=' + str(v.id) + '">📝 Testes</a>'
    h += '<a class="btn cinza" href="/monitoramento?vaga=' + str(v.id) + '">📊 Monitoramento</a></div>'
    etapas = ConfigEtapa.query.filter_by(vaga_id=v.id).order_by(ConfigEtapa.ordem).all()
    if not etapas:
        criar_etapas_padrao(v.id)
        etapas = ConfigEtapa.query.filter_by(vaga_id=v.id).order_by(ConfigEtapa.ordem).all()
    h += '<div class="painel"><h4>Etapas do Funil (prazos e metas)</h4>'
    h += '<table class="tabela"><thead><tr><th>#</th><th>Etapa</th><th>SLA (dias)</th><th>Teste</th><th>Atividades</th><th>Ações</th></tr></thead><tbody>'
    for e in etapas:
        teste = '✅ Sim' if e.tem_teste else '—'
        h += ('<tr><td>' + str(e.ordem) + '</td><td><b>' + e.nome + '</b></td>'
              '<td><input type="number" id="sla_' + str(e.id) + '" value="' + str(e.sla_dias) + '" style="width:70px"></td>'
              '<td>' + teste + '</td>'
              '<td><input id="atv_' + str(e.id) + '" value="' + (e.atividades or '') + '" style="width:100%"></td>'
              '<td><button class="kbtn" onclick="salvarEtapa(' + str(e.id) + ')">💾</button> '
              '<button class="kbtn" onclick="removerEtapa(' + str(e.id) + ')">🗑️</button></td></tr>')
    h += '</tbody></table>'
    h += '<h4 style="margin-top:14px">➕ Nova etapa</h4><form id="f">'
    h += '<div class="status" style="align-items:flex-end">'
    h += '<div style="flex:1"><label>Nome da etapa</label><input id="nome" required placeholder="ex: Teste Prático"></div>'
    h += '<div style="width:100px"><label>SLA (dias)</label><input id="sla" type="number" value="3"></div>'
    h += '<div><label>Tem teste?</label><select id="tem_teste"><option value="0">Não</option><option value="1">Sim</option></select></div>'
    h += '<div style="flex:2"><label>Atividades da fase</label><input id="atividades" placeholder="O que acontece nesta etapa?"></div>'
    h += '<div><button class="btn" type="submit">Adicionar</button></div></div></form>'
    h += '<div class="mensagem" id="msg"></div></div>'
    h += ('<script>'
          'document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/etapas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({vaga_id:' + str(v.id) + ',nome:document.getElementById("nome").value,'
          'sla_dias:document.getElementById("sla").value,tem_teste:document.getElementById("tem_teste").value==="1",'
          'atividades:document.getElementById("atividades").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Etapa adicionada! Atualizando...";setTimeout(function(){location.reload();},600);}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};'
          'function salvarEtapa(id){fetch("/api/etapas/"+id+"/atualizar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({sla_dias:document.getElementById("sla_"+id).value,atividades:document.getElementById("atv_"+id).value})})'
          '.then(function(r){return r.json();}).then(function(j){alert(j.msg||j.erro);});}'
          'function removerEtapa(id){if(!confirm("Remover esta etapa?")){return;}'
          'fetch("/api/etapas/"+id+"/remover",{method:"POST"}).then(function(r){return r.json();})'
          '.then(function(j){if(j.ok){location.reload();}else{alert(j.erro);}});}</script>')
    return pagina(h, '/config-etapas')

@app.route('/api/etapas/cadastrar', methods=['POST'])
def api_etapas_cadastrar():
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    v = Vaga.query.get(d.get('vaga_id', type=int))
    if not v:
        return jsonify({'erro': 'Vaga não encontrada'}), 404
    nome = (d.get('nome') or '').strip()
    if not nome:
        return jsonify({'erro': 'Informe o nome da etapa'}), 400
    max_ordem = db.session.query(db.func.max(ConfigEtapa.ordem)).filter_by(vaga_id=v.id).scalar() or 0
    e = ConfigEtapa(vaga_id=v.id, nome=nome, ordem=max_ordem + 1,
                    sla_dias=int(d.get('sla_dias') or 3),
                    tem_teste=bool(d.get('tem_teste', False)),
                    atividades=(d.get('atividades') or '').strip())
    db.session.add(e)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Etapa adicionada'})

@app.route('/api/etapas/<int:eid>/atualizar', methods=['POST'])
def api_etapas_atualizar(eid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    e = ConfigEtapa.query.get(eid)
    if not e:
        return jsonify({'erro': 'Etapa não encontrada'}), 404
    d = request.get_json(force=True)
    try:
        e.sla_dias = int(d.get('sla_dias') or e.sla_dias)
    except Exception:
        pass
    e.atividades = (d.get('atividades') or '').strip() or e.atividades
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Etapa atualizada'})

@app.route('/api/etapas/<int:eid>/remover', methods=['POST'])
def api_etapas_remover(eid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    e = ConfigEtapa.query.get(eid)
    if not e:
        return jsonify({'erro': 'Etapa não encontrada'}), 404
    db.session.delete(e)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Etapa removida'})

# ================= V10: TESTES =================
@app.route('/testes')
@gestor_required
def testes():
    vaga_id = request.args.get('vaga', type=int)
    vagas = Vaga.query.order_by(Vaga.id.desc()).all()
    v = Vaga.query.get(vaga_id) if vaga_id else (vagas[0] if vagas else None)
    if not v:
        return pagina('<h1>Nenhuma vaga cadastrada</h1>', '/')
    h = '<h1>📝 Testes <span>// ' + v.titulo + '</span></h1>'
    h += '<p class="sub">Cadastre os testes de cada fase e lance as notas dos candidatos.</p>'
    h += '<div class="caixa-busca"><select onchange="location.href=\'/testes?vaga=\'+this.value">'
    for vg in vagas:
        sel = ' selected' if vg.id == v.id else ''
        h += '<option value="' + str(vg.id) + '"' + sel + '>💼 ' + vg.titulo + '</option>'
    h += '</select><a class="btn cinza" href="/config-etapas?vaga=' + str(v.id) + '">🧪 Etapas</a>'
    h += '<a class="btn cinza" href="/monitoramento?vaga=' + str(v.id) + '">📊 Monitoramento</a></div>'
    h += '<div class="painel" style="max-width:640px"><h4>➕ Cadastrar teste</h4><form id="f">'
    h += '<label>Nome do teste *</label><input id="nome" required placeholder="ex: Teste Técnico Python">'
    h += '<label>Tipo</label><select id="tipo"><option value="tecnico">💻 Técnico</option><option value="comportamental">🧠 Comportamental</option><option value="idioma">🗣️ Idioma</option><option value="logica">🧩 Lógica</option></select>'
    h += '<label>Etapa relacionada</label><select id="etapa_nome"><option value="">—</option>'
    for ce in ConfigEtapa.query.filter_by(vaga_id=v.id).order_by(ConfigEtapa.ordem).all():
        h += '<option value="' + ce.nome + '">' + ce.nome + '</option>'
    h += '</select>'
    h += '<label>Nota máxima</label><input id="nota_max" type="number" value="10" step="0.5">'
    h += '<div style="margin-top:12px"><button class="btn" type="submit">Cadastrar teste</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    testes_lista = Teste.query.filter_by(vaga_id=v.id).order_by(Teste.id.desc()).all()
    candidaturas = Candidatura.query.filter_by(vaga_id=v.id).all()
    if not testes_lista:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhum teste cadastrado ainda para esta vaga.</p></div>'
    for t in testes_lista:
        h += '<div class="painel"><h4>📝 ' + t.nome + ' • ' + t.tipo + ' • Nota máx: ' + str(int(t.nota_max)) + '</h4>'
        h += '<p style="color:#8fa3c0;font-size:12px;margin-bottom:10px">Etapa: ' + (t.etapa_nome or '—') + '</p>'
        h += '<table class="tabela"><thead><tr><th>Candidato</th><th>Nota</th><th>Status</th><th>Salvar</th></tr></thead><tbody>'
        for c in candidaturas:
            cand = Usuario.query.get(c.candidato_id)
            r = ResultadoTeste.query.filter_by(teste_id=t.id, candidato_id=c.candidato_id).first()
            valor = str(int(r.nota)) if r and r.nota is not None else ''
            if r and r.status != 'pendente':
                status = '<span class="pill ' + r.status + '">' + r.status + '</span>'
            else:
                status = '<span class="pill pendente">pendente</span>'
            h += ('<tr><td><b>' + (cand.nome if cand else '-') + '</b></td>'
                  '<td><input id="nota_' + str(t.id) + '_' + str(c.candidato_id) + '" type="number" min="0" step="0.5" value="' + valor + '" style="width:80px"></td>'
                  '<td>' + status + '</td>'
                  '<td><button class="kbtn" onclick="salvarNota(' + str(t.id) + ',' + str(c.candidato_id) + ')">💾</button></td></tr>')
        h += '</tbody></table></div>'
    h += ('<script>'
          'document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/testes/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({vaga_id:' + str(v.id) + ',nome:document.getElementById("nome").value,'
          'tipo:document.getElementById("tipo").value,etapa_nome:document.getElementById("etapa_nome").value,'
          'nota_max:document.getElementById("nota_max").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Teste cadastrado!";setTimeout(function(){location.reload();},600);}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};'
          'function salvarNota(tid,cid){var n=document.getElementById("nota_"+tid+"_"+cid).value;'
          'fetch("/api/testes/resultado",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({teste_id:tid,candidato_id:cid,nota:n})})'
          '.then(function(r){return r.json();}).then(function(j){if(j.ok){location.reload();}else{alert(j.erro);}});}</script>')
    return pagina(h, '/testes')

@app.route('/api/testes/cadastrar', methods=['POST'])
def api_teste_cadastrar():
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    v = Vaga.query.get(d.get('vaga_id', type=int))
    if not v:
        return jsonify({'erro': 'Vaga não encontrada'}), 404
    nome = (d.get('nome') or '').strip()
    if not nome:
        return jsonify({'erro': 'Informe o nome do teste'}), 400
    t = Teste(vaga_id=v.id, nome=nome, tipo=(d.get('tipo') or 'tecnico'),
              etapa_nome=(d.get('etapa_nome') or '').strip(),
              nota_max=parse_float(d.get('nota_max')) or 10.0)
    db.session.add(t)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Teste cadastrado'})

@app.route('/api/testes/resultado', methods=['POST'])
def api_teste_resultado():
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    t = Teste.query.get(d.get('teste_id', type=int))
    cand = Usuario.query.get(d.get('candidato_id', type=int))
    if not t or not cand or cand.tipo != 'candidato':
        return jsonify({'erro': 'Teste ou candidato inválido'}), 400
    r = ResultadoTeste.query.filter_by(teste_id=t.id, candidato_id=cand.id).first()
    if not r:
        r = ResultadoTeste(teste_id=t.id, candidato_id=cand.id, vaga_id=t.vaga_id)
        db.session.add(r)
    nota = parse_float(d.get('nota'))
    if nota is None:
        r.nota = None
        r.status = 'pendente'
        r.realizado_em = None
    else:
        r.nota = nota
        r.status = 'aprovado' if nota >= (t.nota_max or 10) * 0.7 else 'reprovado'
        r.realizado_em = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Resultado salvo', 'status': r.status})

# ================= V10: MONITORAMENTO =================
@app.route('/monitoramento')
@gestor_required
def monitoramento():
    vaga_id = request.args.get('vaga', type=int)
    vagas = Vaga.query.order_by(Vaga.criada_em).all()
    v = Vaga.query.get(vaga_id) if vaga_id else (vagas[0] if vagas else None)
    agora = datetime.utcnow()
    h = '<h1>📊 Monitoramento <span>// Funil e prazos</span></h1>'
    h += '<p class="sub">Controle de prazos por etapa, tempo de abertura das vagas e fatores do processo.</p>'
    h += '<div class="caixa-busca"><select onchange="location.href=\'/monitoramento?vaga=\'+this.value">'
    for vg in vagas:
        sel = ' selected' if v and vg.id == v.id else ''
        h += '<option value="' + str(vg.id) + '"' + sel + '>💼 ' + vg.titulo + '</option>'
    h += '</select><a class="btn cinza" href="/config-etapas?vaga=' + str((v.id if v else 0)) + '">🧪 Etapas</a>'
    h += '<a class="btn cinza" href="/financeiro">💰 Financeiro</a></div>'
    h += '<div class="painel"><h4>Indicadores</h4><div class="status">'
    h += '<div class="item"><span class="dot ciano"></span> Vagas abertas: <b>' + str(Vaga.query.filter_by(status='aberta').count()) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(Candidatura.query.count()) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> Contratados: <b>' + str(Candidatura.query.filter_by(status='aprovado').count()) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Entrevistas: <b>' + str(Entrevista.query.count()) + '</b></div>'
    h += '</div></div>'
    h += '<div class="painel"><h4>Vagas abertas por tempo (dias)</h4>'
    h += '<table class="tabela"><thead><tr><th>Vaga</th><th>Dias abertos</th><th>Candidaturas</th><th>Entrevistas</th><th>Status</th></tr></thead><tbody>'
    for vg in vagas:
        dias = (agora - vg.criada_em).days if vg.criada_em else 0
        cor = '#10b981' if dias < 15 else ('#f59e0b' if dias < 30 else '#ef4444')
        n_cands = Candidatura.query.filter_by(vaga_id=vg.id).count()
        n_ents = Entrevista.query.filter_by(vaga_id=vg.id).count()
        sel = ' style="background:rgba(15,33,64,.6)"' if v and vg.id == v.id else ''
        h += ('<tr' + sel + '><td><b>' + vg.titulo + '</b></td>'
              '<td><b style="color:' + cor + '">' + str(dias) + ' dias</b></td>'
              '<td>' + str(n_cands) + '</td><td>' + str(n_ents) + '</td>'
              '<td><span class="pill ' + vg.status + '">' + vg.status + '</span></td></tr>')
    h += '</tbody></table></div>'
    if v:
        h += '<div class="painel"><h4>SLA por etapa — ' + v.titulo + '</h4>'
        etapas = ConfigEtapa.query.filter_by(vaga_id=v.id).order_by(ConfigEtapa.ordem).all()
        if not etapas:
            h += '<p style="color:#8fa3c0">Nenhuma etapa configurada. <a class="link" href="/config-etapas?vaga=' + str(v.id) + '">Configurar →</a></p>'
        else:
            h += '<table class="tabela"><thead><tr><th>Etapa</th><th>SLA</th><th>Candidatos</th><th>Maior tempo na etapa</th><th>Situação</th></tr></thead><tbody>'
            for ce in etapas:
                cands_etapa = []
                for c in Candidatura.query.filter_by(vaga_id=v.id).all():
                    cfg = achar_config_etapa(v.id, c.etapa)
                    if cfg and cfg.id == ce.id:
                        cands_etapa.append(c)
                maior = 0
                for c in cands_etapa:
                    d = dias_na_etapa(c)
                    if d > maior:
                        maior = d
                if cands_etapa:
                    alerta = '<span class="pill fechada">⚠️ Acima do SLA</span>' if maior > ce.sla_dias else '<span class="pill realizada">✅ Dentro do prazo</span>'
                else:
                    alerta = '<span style="color:#8fa3c0;font-size:12px">sem candidatos</span>'
                h += ('<tr><td><b>' + ce.nome + '</b></td><td>' + str(ce.sla_dias) + ' dias</td>'
                      '<td>' + str(len(cands_etapa)) + '</td><td>' + (str(maior) + ' dias' if cands_etapa else '—') + '</td>'
                      '<td>' + alerta + '</td></tr>')
            h += '</tbody></table>'
            h += '<p style="color:#8fa3c0;font-size:12px;margin-top:10px">💡 O tempo na etapa é medido desde a última movimentação no Pipeline (Passo 2 registra a data automaticamente).</p>'
        h += '</div>'
    return pagina(h, '/monitoramento')

# ================= V10: FINANCEIRO =================
@app.route('/financeiro')
@gestor_required
def financeiro():
    vaga_id = request.args.get('vaga', type=int)
    vagas = Vaga.query.order_by(Vaga.id.desc()).all()
    h = '<h1>💰 Financeiro <span>// Custos e comissões</span></h1>'
    h += '<p class="sub">Gestão financeira das vagas: custo, comissão do analista, comissão do RH e emissão de notas fiscais.</p>'
    lancs = Financa.query.all()
    if vaga_id:
        lancs = [f for f in lancs if f.vaga_id == vaga_id]
    total = sum(f.valor or 0 for f in lancs)
    pendente = sum(f.valor or 0 for f in lancs if f.status in ('pendente', 'emitido'))
    pago = sum(f.valor or 0 for f in lancs if f.status == 'pago')
    h += '<div class="painel"><h4>Resumo</h4><div class="status">'
    h += '<div class="item"><span class="dot ciano"></span> Lançamentos: <b>' + str(len(lancs)) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Total: <b>' + texto_int(total) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> A receber: <b>' + texto_int(pendente) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Pago: <b>' + texto_int(pago) + '</b></div>'
    h += '</div></div>'
    h += '<div class="caixa-busca"><select onchange="location.href=\'/financeiro?vaga=\'+this.value">'
    h += '<option value="">Todas as vagas</option>'
    for vg in vagas:
        sel = ' selected' if vaga_id == vg.id else ''
        h += '<option value="' + str(vg.id) + '"' + sel + '>💼 ' + vg.titulo + '</option>'
    h += '</select></div>'
    h += '<div class="painel" style="max-width:640px"><h4>➕ Novo lançamento</h4><form id="f">'
    h += '<label>Vaga *</label><select id="vaga_id" required><option value="">Selecione...</option>'
    for vg in vagas:
        h += '<option value="' + str(vg.id) + '">' + vg.titulo + '</option>'
    h += '</select>'
    h += '<label>Tipo *</label><select id="tipo">'
    for k, label in TIPO_FINANCA.items():
        h += '<option value="' + k + '">' + label + '</option>'
    h += '</select>'
    h += '<label>Descrição</label><input id="descricao" placeholder="ex: Comissão pela contratação do Desenvolvedor Python">'
    h += '<label>Valor (R$) *</label><input id="valor" type="number" step="0.01" required placeholder="ex: 1500">'
    h += '<div style="margin-top:12px"><button class="btn" type="submit">Adicionar lançamento</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    if not lancs:
        h += '<div class="painel"><p style="color:#8fa3c0">Nenhum lançamento financeiro ainda.</p></div>'
    else:
        h += '<div class="painel"><h4>Lançamentos</h4><table class="tabela"><thead><tr><th>Vaga</th><th>Tipo</th><th>Descrição</th><th>Valor</th><th>Status</th><th>NF</th><th>Ações</th></tr></thead><tbody>'
        for f in lancs:
            v = Vaga.query.get(f.vaga_id)
            nf = f.nota_fiscal or '—'
            acoes = ''
            if f.status in ('pendente', 'emitido'):
                acoes += '<button class="kbtn" onclick="pagar(' + str(f.id) + ')">✅ Pagar</button>'
            if not f.nota_fiscal:
                acoes += '<button class="kbtn" onclick="emitirNF(' + str(f.id) + ')">🧾 Emitir NF</button>'
            h += ('<tr><td>' + (v.titulo if v else '-') + '</td><td>' + TIPO_FINANCA.get(f.tipo, f.tipo) + '</td>'
                  '<td>' + (f.descricao or '') + '</td><td><b style="color:#22d3ee">' + texto_int(f.valor) + '</b></td>'
                  '<td><span class="pill ' + f.status + '">' + f.status + '</span></td><td>' + nf + '</td>'
                  '<td><div class="kbtns">' + acoes + '</div></td></tr>')
        h += '</tbody></table></div>'
    h += ('<script>'
          'document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/financas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({vaga_id:document.getElementById("vaga_id").value,'
          'tipo:document.getElementById("tipo").value,descricao:document.getElementById("descricao").value,'
          'valor:document.getElementById("valor").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){m.className="mensagem ok";'
          'm.innerHTML="✅ Lançamento adicionado!";setTimeout(function(){location.reload();},600);}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};'
          'function pagar(fid){fetch("/api/financas/"+fid+"/pagar",{method:"POST"}).then(function(r){return r.json();})'
          '.then(function(j){if(j.ok){location.reload();}else{alert(j.erro);}});}'
          'function emitirNF(fid){fetch("/api/financas/"+fid+"/emitir-nf",{method:"POST"}).then(function(r){return r.json();})'
          '.then(function(j){if(j.ok){alert(j.msg);location.reload();}else{alert(j.erro);}});}</script>')
    return pagina(h, '/financeiro')

@app.route('/api/financas/cadastrar', methods=['POST'])
def api_financa_cadastrar():
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    d = request.get_json(force=True)
    v = Vaga.query.get(d.get('vaga_id', type=int))
    if not v:
        return jsonify({'erro': 'Selecione a vaga'}), 400
    valor = parse_float(d.get('valor'))
    if valor is None or valor < 0:
        return jsonify({'erro': 'Valor inválido'}), 400
    f = Financa(vaga_id=v.id, tipo=(d.get('tipo') or 'custo_vaga'),
                descricao=(d.get('descricao') or '').strip(), valor=valor, status='pendente')
    db.session.add(f)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Lançamento adicionado'})

@app.route('/api/financas/<int:fid>/pagar', methods=['POST'])
def api_financa_pagar(fid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    f = Financa.query.get(fid)
    if not f:
        return jsonify({'erro': 'Lançamento não encontrado'}), 404
    f.status = 'pago'
    f.paga_em = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Lançamento marcado como pago'})

@app.route('/api/financas/<int:fid>/emitir-nf', methods=['POST'])
def api_financa_emitir_nf(fid):
    u = usuario_atual()
    if not u or u.tipo not in ('admin', 'empresa'):
        return jsonify({'erro': 'Acesso restrito'}), 403
    f = Financa.query.get(fid)
    if not f:
        return jsonify({'erro': 'Lançamento não encontrado'}), 404
    if f.nota_fiscal:
        return jsonify({'erro': 'NF já emitida: ' + f.nota_fiscal}), 400
    ano = datetime.utcnow().year
    seq = Financa.query.filter(Financa.nota_fiscal.isnot(None)).count() + 1
    f.nota_fiscal = 'NF-' + str(ano) + '-' + str(seq).zfill(4)
    f.status = 'emitido'
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'NF emitida: ' + f.nota_fiscal, 'nota_fiscal': f.nota_fiscal})

# ================= V10: MIGRACAO =================
with app.app_context():
    db.create_all()
    try:
        db.session.execute(text("ALTER TABLE candidatura ADD COLUMN IF NOT EXISTS etapa_atualizada_em DATETIME"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    for _v in Vaga.query.all():
        criar_etapas_padrao(_v.id)
# ================= V11: GRUPOS E PERMISSOES (APIS) =================
@app.route('/api/admin/grupos/permissoes', methods=['POST'])
def api_admin_grupo_permissoes():
    u = usuario_atual()
    if not u or u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito ao administrador'}), 403
    d = request.get_json(force=True)
    grupo = (d.get('grupo') or '').strip()
    if grupo not in GRUPOS:
        return jsonify({'erro': 'Grupo inválido'}), 400
    perms = d.get('permissoes') or {}
    for mod in MODULOS_GERENCIAVEIS:
        gp = GrupoPermissao.query.filter_by(grupo=grupo, modulo=mod).first()
        if not gp:
            gp = GrupoPermissao(grupo=grupo, modulo=mod)
            db.session.add(gp)
        if mod in perms:
            gp.habilitado = bool(perms[mod])
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Permissões do grupo salvas!'})

@app.route('/api/admin/usuario/grupo', methods=['POST'])
def api_admin_usuario_grupo():
    u = usuario_atual()
    if not u or u.tipo != 'admin':
        return jsonify({'erro': 'Acesso restrito ao administrador'}), 403
    d = request.get_json(force=True)
    alvo = Usuario.query.get(d.get('usuario_id', type=int))
    if not alvo or alvo.tipo == 'admin':
        return jsonify({'erro': 'Usuário inválido'}), 400
    grupo = (d.get('grupo') or '').strip()
    if grupo not in GRUPOS:
        return jsonify({'erro': 'Grupo inválido'}), 400
    alvo.grupo = grupo
    if 'ativo' in d:
        alvo.ativo = bool(d.get('ativo'))
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Usuário atualizado!'})

# ================= V11: MIGRACAO DO CAMPO GRUPO =================
with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE usuario ADD COLUMN IF NOT EXISTS grupo VARCHAR(30)"))
        db.session.commit()
    except Exception:
        db.session.rollback()
# ================= INICIO =================
with app.app_context():
    db.create_all()
    try:
        db.session.execute("ALTER TABLE candidatura ADD COLUMN IF NOT EXISTS etapa VARCHAR(20) DEFAULT 'triagem'")
        db.session.commit()
    except Exception:
        db.session.rollback()
    criar_dados_iniciais()
    garantir_dados_demo()
    garantir_permissoes()

if __name__ == '__main__':
    print()
    print('=' * 56)
    print('  🌐 ECOSSISTEMA DE RH INOVADOR v10.0')
    print('  ⚙️ Permissoes + Edicao de candidatos + Chat')
    print('=' * 56)
    print('  🔗 Menu:        http://localhost:5000')
    print('  ⚙️ Gerenciar:   http://localhost:5000/gerenciar')
    print('=' * 56)
    print('  Pressione CTRL+C para parar')
    print()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
