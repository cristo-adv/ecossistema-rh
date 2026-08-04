# -*- coding: utf-8 -*-
"""Ecossistema de RH Inovador v6.0 — pipeline kanban, visual inovador, ranking e cadastro."""

import os
import re
import random
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from flask_socketio import SocketIO, emit
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

class Empresa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    razao_social = db.Column(db.String(200))
    nome_fantasia = db.Column(db.String(120))
    cnpj = db.Column(db.String(20))
    porte = db.Column(db.String(30))
    setor = db.Column(db.String(60))
    descricao = db.Column(db.Text)
    cultura = db.Column(db.Text)

class Trilha(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False)
    descricao = db.Column(db.String(250))

class Nivel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trilha_id = db.Column(db.Integer, db.ForeignKey('trilha.id'))
    codigo = db.Column(db.String(10), nullable=False)
    nome = db.Column(db.String(60), nullable=False)
    ordem = db.Column(db.Integer)
    salario_min = db.Column(db.Float)
    salario_max = db.Column(db.Float)
    autonomia = db.Column(db.String(60))
    impacto = db.Column(db.String(60))

class Vaga(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text)
    empresa = db.Column(db.String(120))
    nivel_codigo = db.Column(db.String(10))
    status = db.Column(db.String(20), default='aberta')
    salario_min = db.Column(db.Float)
    salario_max = db.Column(db.Float)
    regime = db.Column(db.String(30))
    localizacao = db.Column(db.String(120))
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

class Requisito(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    skill = db.Column(db.String(100))

class Candidatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    candidato_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    match_score = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pendente')
    etapa = db.Column(db.String(20), default='triagem')
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

# ================= HELPERS =================
def parse_float(s):
    if not s:
        return None
    s = str(s).strip().replace('R$', '').replace(' ', '')
    if not s:
        return None
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None

def texto_int(valor):
    if valor is None:
        return '-'
    return 'R$ ' + format(int(valor), ',d').replace(',', '.')

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
        nav.append(('/perfil', '👤', 'Meu Perfil'))
        nav.append(('/importar-plano', '📥', 'Importar Plano'))
        if u.tipo in ('admin', 'empresa'):
            nav.append(('/pipeline', '📋', 'Pipeline'))
            nav.append(('/cadastrar-candidato', '👤➕', 'Cadastrar Candidato'))
        nav.append(('/painel', '🔑', 'Meu Painel'))
    itens = ''
    for href, icone, nome in nav:
        cls = ' class="ativo"' if href == ativo else ''
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
.pill.aberta,.pill.candidato,.pill.contratado{background:rgba(16,185,129,.14);color:#10b981}
.pill.fechada,.pill.rejeitado{background:rgba(239,68,68,.14);color:#ef4444}
.pill.empresa{background:rgba(245,158,11,.14);color:#f59e0b}
.pill.admin{background:rgba(168,85,247,.14);color:#a855f7}
.pill.pendente,.pill.triagem,.pill.proposta{background:rgba(245,158,11,.14);color:#f59e0b}
.pill.entrevista{background:rgba(34,211,238,.14);color:#22d3ee}
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
.kbtns{display:flex;gap:6px;margin-top:8px}
.kbtn{background:rgba(30,41,59,.9);color:#fff;border:1px solid rgba(59,130,246,.35);border-radius:6px;padding:4px 9px;font-size:11px;cursor:pointer}
.kbtn:hover{background:#1d4ed8}
.kbtn.verde:hover{background:#059669}
footer{margin-top:24px;color:#475569;font-size:12px}
@media(max-width:800px){body{flex-direction:column}aside{width:100%;border-right:none;border-bottom:1px solid rgba(28,47,74,.7)}main{padding:18px}}
</style></head><body>
<aside><h2>⚡ ECOSSISTEMA RH</h2><nav>@NAV@</nav></aside>
<main><header><h1>Ecossistema RH <span>// Inovador</span></h1>@CHIP@</header>
@CONTEUDO@
<footer>Ecossistema de RH Inovador v6.0 — dados permanentes | conexões em tempo real: <span id="conn">0/@MAX@</span></footer>
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

# ================= PIPELINE (KANBAN) =================
@app.route('/pipeline')
@gestor_required
def pipeline():
    u = usuario_atual()
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

# ================= MEU PAINEL =================
@app.route('/painel')
@login_required
def painel():
    u = usuario_atual()
    h = '<h1>Meu Painel <span>// ' + u.nome + '</span></h1><p class="sub">Acompanhe suas atividades no ecossistema.</p>'
    if u.tipo == 'candidato':
        p = Perfil.query.filter_by(usuario_id=u.id).first()
        if p and p.skills:
            h += '<div class="painel"><h4>Minhas Skills</h4><div class="status">'
            for sk in [s.strip() for s in p.skills.split(',') if s.strip()]:
                h += '<span class="pill candidato">' + sk + '</span>'
            h += ' <a class="link" href="/perfil">editar →</a></div></div>'
        cands = Candidatura.query.filter_by(candidato_id=u.id).order_by(Candidatura.id.desc()).all()
        h += '<div class="painel"><h4>Minhas Candidaturas</h4>'
        if cands:
            h += '<table class="tabela"><thead><tr><th>Vaga</th><th>Empresa</th><th>Match Score</th><th>Etapa</th><th>Status</th><th>Data</th></tr></thead><tbody>'
            for c in cands:
                v = Vaga.query.get(c.vaga_id)
                et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
                h += ('<tr><td><b><a class="link" href="/vagas/' + str(v.id) + '">' + (v.titulo if v else 'Vaga') + '</a></b></td><td>' + (v.empresa if v else '-') + '</td>'
                      '<td><b style="color:#22d3ee">' + str(int(c.match_score)) + '%</b></td>'
                      '<td><span class="pill ' + et + '">' + ETAPAS_INFO[et][0] + '</span></td>'
                      '<td><span class="pill ' + c.status + '">' + c.status + '</span></td>'
                      '<td>' + c.criada_em.strftime('%d/%m/%Y') + '</td></tr>')
            h += '</tbody></table>'
        else:
            h += '<p style="color:#8fa3c0">Você ainda não se candidatou. <a class="link" href="/vagas">Ver vagas abertas →</a></p>'
        h += '</div>'
        h += '<div class="painel"><h4>Estatísticas</h4><div class="status">'
        h += '<div class="item"><span class="dot ciano"></span> Candidaturas: <b>' + str(len(cands)) + '</b></div>'
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
        h += '<a class="btn cinza" href="/importar-plano">📥 Importar Plano PCS</a>'
        h += '</div></div>'
    else:
        h += '<div class="painel"><h4>Visão Geral (Administrador)</h4><div class="status">'
        h += '<div class="item"><span class="dot"></span> Candidatos: <b>' + str(Usuario.query.filter_by(tipo='candidato').count()) + '</b></div>'
        h += '<div class="item"><span class="dot ciano"></span> Empresas: <b>' + str(Usuario.query.filter_by(tipo='empresa').count()) + '</b></div>'
        h += '<div class="item"><span class="dot roxo"></span> Vagas: <b>' + str(Vaga.query.count()) + '</b></div>'
        h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(Candidatura.query.count()) + '</b></div>'
        h += '</div></div>'
        h += '<div class="painel"><h4>Atalhos</h4><div class="status">'
        h += '<a class="btn" href="/cadastrar-vaga">➕ Publicar Vaga</a> '
        h += '<a class="btn" href="/cadastrar-candidato">👤➕ Cadastrar Candidato</a> '
        h += '<a class="btn" href="/pipeline">📋 Pipeline</a> '
        h += '<a class="btn verde" href="/importar-plano">📥 Importar Plano PCS</a> '
        h += '<a class="btn cinza" href="/cadastrar-empresa">🏢 Cadastrar Empresa</a> '
        h += '<a class="btn cinza" href="/analytics">📈 Analytics</a>'
        h += '</div></div>'
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
    h += '<div class="item"><span class="dot"></span> Módulos: <b>11</b></div>'
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
    if u:
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
    if u and u.tipo in ('admin', 'empresa'):
        h += '<a class="btn cinza" href="/vagas/' + str(vid) + '/ranking">🏆 Ver Ranking</a>'
        h += '<a class="btn cinza" href="/pipeline?vaga=' + str(vid) + '">📋 Ver Pipeline</a>'
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
        h += '<div class="painel"><table class="tabela"><thead><tr><th>Posição</th><th>Candidato</th><th>E-mail</th><th>Match Score</th><th>Etapa</th><th>Status</th></tr></thead><tbody>'
        for i, c in enumerate(cands):
            cand = Usuario.query.get(c.candidato_id)
            pos = i + 1
            medalha = medalhas[i] if i < 3 else '<span class="medalha">' + str(pos) + 'º</span>'
            cor_score = '#10b981' if c.match_score >= 80 else ('#f59e0b' if c.match_score >= 65 else '#ef4444')
            et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
            h += ('<tr><td>' + medalha + '</td><td><b>' + (cand.nome if cand else '-') + '</b></td>'
                  '<td>' + (cand.email if cand else '-') + '</td>'
                  '<td><b style="color:' + cor_score + '">' + str(int(c.match_score)) + '%</b></td>'
                  '<td><span class="pill ' + et + '">' + ETAPAS_INFO[et][0] + '</span></td>'
                  '<td><span class="pill ' + c.status + '">' + c.status + '</span></td></tr>')
        h += '</tbody></table></div>'
        melhor = cands[0]
        cand_top = Usuario.query.get(melhor.candidato_id)
        if cand_top:
            h += '<div class="painel"><h4>⭐ Melhor Candidato</h4><p style="font-size:14px">'
            h += '<b>' + cand_top.nome + '</b> lidera com <b style="color:#22d3ee">' + str(int(melhor.match_score)) + '%</b> de compatibilidade.</p></div>'
    h += '<div class="status"><a class="btn cinza" href="/vagas/' + str(vid) + '">← Voltar para a vaga</a> '
    h += '<a class="btn cinza" href="/pipeline?vaga=' + str(vid) + '">📋 Ver Pipeline</a></div>'
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
def pagina_cadastrar_empresa():
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
    h = '<h1>Candidatos <span>// Talentos</span></h1>'
    h += '<p class="sub">' + str(len(lista)) + ' profissionais no ecossistema</p>'
    h += '<div class="painel"><table class="tabela"><thead><tr><th>Nome</th><th>E-mail</th><th>Skills</th><th>Candidaturas</th><th>Status</th></tr></thead><tbody>'
    for u in lista:
        p = Perfil.query.filter_by(usuario_id=u.id).first()
        total = Candidatura.query.filter_by(candidato_id=u.id).count()
        skills = (p.skills[:60] + '...') if p and p.skills and len(p.skills) > 60 else (p.skills if p else '-')
        h += ('<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td>' + (skills or '-') + '</td>'
              '<td>' + str(total) + '</td>'
              '<td><span class="pill candidato">Ativo</span></td></tr>')
    h += '</tbody></table></div>'
    return pagina(h, '/candidatos')

@app.route('/empresas')
def empresas():
    lista = Usuario.query.filter_by(tipo='empresa').all()
    h = '<h1>Empresas <span>// Contratantes</span></h1>'
    h += '<p class="sub">' + str(len(lista)) + ' organizações no ecossistema</p>'
    h += '<div class="painel"><p><a class="btn cinza" href="/cadastrar-empresa">➕ Cadastrar Empresa</a></p></div>'
    h += '<div class="painel"><table class="tabela"><thead><tr><th>Razão Social</th><th>E-mail</th><th>Setor</th><th>Status</th></tr></thead><tbody>'
    for u in lista:
        emp = Empresa.query.filter_by(usuario_id=u.id).first()
        h += ('<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td>' + (emp.setor if emp else '-') + '</td>'
              '<td><span class="pill aberta">Verificada</span></td></tr>')
    h += '</tbody></table></div>'
    return pagina(h, '/empresas')

@app.route('/analytics')
def analytics():
    total_vagas = Vaga.query.count()
    total_candidaturas = Candidatura.query.count()
    total_candidatos = Usuario.query.filter_by(tipo='candidato').count()
    total_empresas = Usuario.query.filter_by(tipo='empresa').count()
    scores = [c.match_score or 0 for c in Candidatura.query.all()]
    score_medio = round(sum(scores) / len(scores), 1) if scores else 0
    h = '<h1>Analytics <span>// People Analytics</span></h1>'
    h += '<p class="sub">KPIs e dashboards em tempo real do ecossistema</p>'
    h += '<div class="painel"><h4>KPIs Principais</h4><div class="status">'
    h += '<div class="item"><span class="dot ciano"></span> Vagas: <b>' + str(total_vagas) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(total_candidaturas) + '</b></div>'
    h += '<div class="item"><span class="dot roxo"></span> Candidatos: <b>' + str(total_candidatos) + '</b></div>'
    h += '<div class="item"><span class="dot"></span> Empresas: <b>' + str(total_empresas) + '</b></div>'
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
    ultimas = Candidatura.query.order_by(Candidatura.id.desc()).limit(10).all()
    if ultimas:
        h += '<div class="painel"><h4>Últimas Candidaturas</h4><table class="tabela"><thead><tr><th>Vaga</th><th>Candidato</th><th>Match</th><th>Etapa</th><th>Status</th></tr></thead><tbody>'
        for c in ultimas:
            v = Vaga.query.get(c.vaga_id)
            u = Usuario.query.get(c.candidato_id)
            et = c.etapa if c.etapa in ETAPAS_INFO else 'triagem'
            h += ('<tr><td>' + (v.titulo if v else '-') + '</td><td>' + (u.nome if u else '-') + '</td>'
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
        ('💭', 'Chat em Tempo Real', 'Mensagens instantâneas, arquivos, grupos por vaga. WebSocket.'),
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
        'status': 'online', 'versao': '6.0.0',
        'conexoes_ativas': conexoes_ativas, 'conexoes_maximas': MAX_CONEXOES,
        'modulos': ['usuarios', 'vagas', 'candidatos', 'empresas', 'pcs', 'conectividade',
                    'recrutamento', 'analytics', 'experiencia', 'inovacao', 'pipeline'],
        'agentes': ['sourcing', 'triagem', 'scheduling', 'followup', 'dei'],
        'trilhas': Trilha.query.count(), 'niveis': Nivel.query.count(), 'vagas': Vaga.query.count(),
        'candidaturas': Candidatura.query.count(),
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
    session['user_id'] = u.id
    if tipo == 'empresa':
        db.session.add(Empresa(usuario_id=u.id, razao_social=nome, nome_fantasia=nome))
        db.session.commit()
    return jsonify({'ok': True, 'msg': 'Conta criada com sucesso',
                    'usuario': {'id': u.id, 'nome': u.nome, 'email': u.email, 'tipo': u.tipo}}), 201

@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.get_json(force=True)
    u = Usuario.query.filter_by(email=(d.get('email') or '').strip()).first()
    if not u or not check_password_hash(u.senha_hash, d.get('senha') or ''):
        return jsonify({'erro': 'Credenciais inválidas'}), 401
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
    d = request.get_json(force=True)
    razao = (d.get('razao_social') or '').strip()
    cnpj = (d.get('cnpj') or '').strip()
    email = (d.get('email') or '').strip()
    if not razao or not cnpj or not email:
        return jsonify({'erro': 'Preencha razão social, CNPJ e e-mail'}), 400
    u = Usuario.query.filter_by(email=email).first()
    if not u:
        u = Usuario(nome=razao, email=email, senha_hash=generate_password_hash('empresa123'),
                    tipo='empresa', ativo=True)
        db.session.add(u)
        db.session.flush()
    emp = Empresa(usuario_id=u.id, razao_social=razao, nome_fantasia=d.get('nome_fantasia'),
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
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidato cadastrado com sucesso',
                    'candidato': {'id': novo.id, 'nome': novo.nome, 'email': novo.email}}), 201

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
    if etapa == 'contratado':
        c.status = 'aprovado'
    elif etapa == 'rejeitado':
        c.status = 'rejeitado'
    elif c.status in ('aprovado', 'rejeitado'):
        c.status = 'pendente'
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidato movido para ' + ETAPAS_INFO[etapa][0], 'etapa': etapa})

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

if __name__ == '__main__':
    print()
    print('=' * 56)
    print('  🌐 ECOSSISTEMA DE RH INOVADOR v6.0')
    print('  📋 Pipeline Kanban + visual inovador')
    print('=' * 56)
    print('  🔗 Menu:    http://localhost:5000')
    print('  📋 Kanban:  http://localhost:5000/pipeline')
    print('=' * 56)
    print('  Pressione CTRL+C para parar')
    print()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
