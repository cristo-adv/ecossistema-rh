# -*- coding: utf-8 -*-
"""Ecossistema de RH Inovador - interface visual completa (arquivo unico)"""
import os, random
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'rh-inovador-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'ecossistema_rh.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app)
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins='*')
MAX_CONEXOES = 5
conexoes_ativas = 0

# ============ MODELOS ============
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    ativo = db.Column(db.Boolean, default=True)

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


# ============ MODELO EMPRESA (perfil completo) ============
class Empresa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    razao_social = db.Column(db.String(200))
    nome_fantasia = db.Column(db.String(120))
    cnpj = db.Column(db.String(20))
    porte = db.Column(db.String(30))
    setor = db.Column(db.String(120))
    descricao = db.Column(db.Text)
    cultura = db.Column(db.Text)
    website = db.Column(db.String(200))

class Candidatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    candidato_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    match_score = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pendente')

# ============ SEED ============
def criar_dados_iniciais():
    if Usuario.query.first():
        return
    db.session.add_all([
        Usuario(nome='Administrador', email='admin@rh.com', senha_hash=generate_password_hash('admin123'), tipo='admin', ativo=True),
        Usuario(nome='Maria Silva', email='candidato@teste.com', senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True),
        Usuario(nome='RH Inovador S.A.', email='empresa@teste.com', senha_hash=generate_password_hash('empresa123'), tipo='empresa', ativo=True),
        Usuario(nome='João Pereira', email='joao@teste.com', senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True),
        Usuario(nome='Ana Souza', email='ana@teste.com', senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True),
    ])
    t1 = Trilha(nome='Carreira Técnica', descricao='Especialização técnica em tecnologia')
    t2 = Trilha(nome='Carreira de Gestão', descricao='Liderança e gestão de pessoas')
    t3 = Trilha(nome='Carreira Comercial', descricao='Vendas e relacionamento com clientes')
    db.session.add_all([t1, t2, t3]); db.session.flush()
    niveis = [
        (t1.id,'EST','Estagiário',1,1200,2500,'Supervisionada','Individual'),
        (t1.id,'JR1','Júnior I',2,2500,4000,'Assistida','Individual'),
        (t1.id,'JR2','Júnior II',3,3500,5500,'Guiada','Individual'),
        (t1.id,'JR3','Júnior III',4,4500,7000,'Moderada','Individual'),
        (t1.id,'PL1','Pleno I',5,6000,9000,'Independente','Time'),
        (t1.id,'PL2','Pleno II',6,8000,12000,'Independente','Time'),
        (t1.id,'PL3','Pleno III',7,10000,15000,'Autônoma','Time'),
        (t1.id,'SR1','Sênior I',8,13000,18000,'Autônoma','Área'),
        (t1.id,'SR2','Sênior II',9,16000,22000,'Proativa','Área'),
        (t1.id,'SR3','Sênior III',10,19000,26000,'Direcionadora','Organização'),
        (t1.id,'MS1','Master I',11,23000,32000,'Visionária','Mercado'),
        (t1.id,'MS2','Master II',12,28000,40000,'Visionária','Indústria'),
        (t1.id,'FEL','Fellow',13,35000,50000,'Autoridade','Sociedade'),
        (t2.id,'GJR','Gestão Júnior',1,5000,8000,'Guiada','Time'),
        (t2.id,'GPL','Gestão Pleno',2,8000,14000,'Independente','Área'),
        (t2.id,'GSR','Gestão Sênior',3,15000,25000,'Estratégica','Organização'),
        (t2.id,'GDIR','Diretoria',4,25000,50000,'Visionária','Mercado'),
        (t3.id,'CJR','Comercial Júnior',1,2500,4500,'Assistida','Individual'),
        (t3.id,'CPL','Comercial Pleno',2,4500,8000,'Independente','Time'),
        (t3.id,'CSR','Comercial Sênior',3,8000,15000,'Estratégica','Área'),
        (t3.id,'CGR','Gerência Comercial',4,15000,30000,'Visionária','Organização'),
    ]
    for tr,cod,nome,ordn,smin,smax,aut,imp in niveis:
        db.session.add(Nivel(trilha_id=tr,codigo=cod,nome=nome,ordem=ordn,salario_min=smin,salario_max=smax,autonomia=aut,impacto=imp))
    db.session.add_all([
        Vaga(titulo='Desenvolvedor(a) Python Pleno', descricao='Flask, SQL e APIs REST. 100% remoto.', empresa='RH Inovador S.A.', nivel_codigo='PL2'),
        Vaga(titulo='Analista de Gente e Gestão', descricao='Suporte ao PCS, carreiras e promoções.', empresa='RH Inovador S.A.', nivel_codigo='GPL'),
        Vaga(titulo='Engenheiro(a) de IA Sênior', descricao='Matching preditivo e agentes autônomos.', empresa='Tech Solutions', nivel_codigo='SR2'),
        Vaga(titulo='Executivo(a) de Contas', descricao='Gestão de carteira de clientes corporativos.', empresa='Tech Solutions', nivel_codigo='CPL'),
        Vaga(titulo='Estagiário(a) de RH', descricao='Apoio ao time de gente e gestão.', empresa='RH Inovador S.A.', nivel_codigo='EST'),
    ])
    db.session.commit()

# ============ WEBSOCKET (limite 5) ============
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

# ============ ESTILO GLOBAL ============
CSS = '''
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
body{background:#0a1628;color:#e5eaf3;min-height:100vh}
header{background:#0d1b30;border-bottom:1px solid #1c2f4a;padding:14px 28px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:10}
header .logo{font-size:18px;font-weight:700;color:#3b82f6;text-decoration:none}
header nav a{color:#9fb0c8;text-decoration:none;font-size:13px;margin-left:16px}
header nav a:hover{color:#fff}
header nav a.ativo{color:#3b82f6}
.container{max-width:1200px;margin:0 auto;padding:28px}
h1{font-size:24px;margin-bottom:6px}
h1 span{color:#3b82f6}
.sub{color:#8fa3c0;font-size:13px;margin-bottom:24px}
.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-bottom:26px}
.card{background:linear-gradient(145deg,#0f2140,#0d1b30);border:1px solid #1c2f4a;border-radius:14px;padding:20px;cursor:pointer;transition:.25s;position:relative;overflow:hidden}
.card:hover{transform:translateY(-4px);border-color:#3b82f6;box-shadow:0 10px 30px rgba(59,130,246,.15)}
.card .icone{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;margin-bottom:12px}
.card h3{font-size:15px;margin-bottom:6px}
.card p{font-size:12px;color:#8fa3c0;line-height:1.5}
.painel{background:#0d1b30;border:1px solid #1c2f4a;border-radius:14px;padding:20px 24px;margin-bottom:24px}
.painel h4{font-size:12px;color:#8fa3c0;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
.status{display:flex;flex-wrap:wrap;gap:18px}
.status .item{display:flex;align-items:center;gap:10px;font-size:14px}
.dot{width:10px;height:10px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981}
.dot.roxo{background:#a855f7;box-shadow:0 0 8px #a855f7}
.dot.ciano{background:#22d3ee;box-shadow:0 0 8px #22d3ee}
.dot.ambar{background:#f59e0b;box-shadow:0 0 8px #f59e0b}
.tabela{width:100%;border-collapse:collapse;font-size:13px}
.tabela th{background:#0f2140;color:#9fb0c8;text-align:left;padding:12px;font-weight:600;border-bottom:1px solid #1c2f4a}
.tabela td{padding:12px;border-bottom:1px solid #16283f;color:#c9d6e8}
.tabela tr:hover td{background:#0f2140}
.barra{height:8px;border-radius:4px;background:#16283f;overflow:hidden;min-width:110px}
.barra span{display:block;height:100%;background:linear-gradient(90deg,#3b82f6,#22d3ee);border-radius:4px}
.pill{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.pill.aberta{background:#10b98122;color:#10b981;border:1px solid #10b98155}
.pill.disp{background:#22d3ee22;color:#22d3ee;border:1px solid #22d3ee55}
footer{margin-top:30px;color:#475569;font-size:12px;text-align:center;padding:20px}
form{display:flex;flex-direction:column;gap:12px;max-width:420px}
label{font-size:13px;color:#9fb0c8}
input,select{padding:11px 14px;background:#0d1b30;border:1px solid #1c2f4a;border-radius:8px;color:#fff;font-size:14px}
input:focus,select:focus{outline:none;border-color:#3b82f6}
button{padding:12px 20px;background:#1d4ed8;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:.2s}
button:hover{background:#2563eb}
.btn-sec{background:#16283f;color:#9fb0c8}
.btn-sec:hover{background:#1c2f4a;color:#fff}
a.link{color:#22d3ee;text-decoration:none;font-size:13px}
.aviso{background:#10b98122;border:1px solid #10b98155;color:#10b981;padding:12px 16px;border-radius:8px;font-size:13px;margin-bottom:16px}
.erro{background:#ef444422;border:1px solid #ef444455;color:#f87171;padding:12px 16px;border-radius:8px;font-size:13px;margin-bottom:16px}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:700px){.duo{grid-template-columns:1fr}}
'''

def pagina(conteudo, ativo=''):
    return '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ecossistema RH Inovador</title><style>' + CSS + '</style></head><body>' + cabecalho(ativo) + '<div class="container">' + conteudo + '</div>' + rodape() + '</body></html>'

def cabecalho(ativo):
    itens = [('/', 'Menu', 'dashboard'), ('/pcs', 'PCS', 'pcs'), ('/vagas', 'Vagas', 'vagas'),
             ('/trilhas', 'Trilhas', 'trilhas'), ('/conectividade', 'Conectividade', 'conect'),
             ('/candidatos', 'Candidatos', 'cand'), ('/empresas', 'Empresas', 'emp'),
             ('/agentes', 'Agentes', 'agent'), ('/login', 'Entrar', 'login')]
    nav = ''
    for url, nome, chave in itens:
        cls = ' ativo' if chave == ativo else ''
        nav += '<a href="' + url + '" class="' + cls + '">' + nome + '</a>'
    return '<header><a class="logo" href="/">⚡ ECOSSISTEMA RH</a><nav>' + nav + '</nav></header>'

def rodape():
    return '<footer>Ecossistema de RH Inovador v1.0 — servidor local | <b id="conn">0/5</b> conexões em tempo real<script>var ws=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host);ws.onmessage=function(e){try{var d=JSON.parse(e.data);if(d.conexoes!==undefined)document.getElementById("conn").textContent=d.conexoes+"/"+d.max;}catch(x){}};setInterval(function(){fetch("/api/health").then(function(r){return r.json()}).then(function(d){document.getElementById("conn").textContent=d.conexoes_ativas+"/"+d.conexoes_maximas}).catch(function(){})},3000);</script></footer>'

def fmt(v):
    return 'R$ ' + format(v, ',.0f').replace(',', '.')

# ============ PAGINAS VISUAIS ============
@app.route('/')
def menu():
    cards = [
        ('🧠','Recrutamento Inteligente','IA generativa, matching preditivo e triagem NLP','#3b82f6','/pcs'),
        ('👤','Candidatos','Perfil blockchain, gamificação e match score','#10b981','/candidatos'),
        ('🏢','Empresas','ATS inteligente, employer branding e talent pool','#f59e0b','/empresas'),
        ('📊','Plano de Cargos e Salários','Níveis Júnior a Fellow, faixas e promoções','#a855f7','/pcs'),
        ('📡','Conectividade','Vídeo, WhatsApp, e-mail e chat em tempo real','#22d3ee','/conectividade'),
        ('💼','Vagas','Oportunidades abertas e candidaturas','#ef4444','/vagas'),
    ]
    html = '<h1>Menu Principal <span>// Ecossistema de RH Inovador</span></h1><p class="sub">Plataforma completa de procura e oferta de empregos — tudo que há de mais inovador</p><div class="grade">'
    for icone, titulo, desc, cor, link in cards:
        html += '<div class="card" onclick="location.href=\'' + link + '\'"><div class="icone" style="background:' + cor + '22">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p></div>'
    html += '</div>'
    html += '<div class="painel"><h4>Status do Servidor</h4><div class="status"><div class="item"><span class="dot"></span> Servidor Online</div><div class="item"><span class="dot ciano"></span> Conexões Ativas: <b id="conn2">0/5</b></div><div class="item"><span class="dot roxo"></span> Agentes Autônomos: <b>5 ativos</b></div><div class="item"><span class="dot ambar"></span> Módulos: <b>10</b></div></div></div>'
    html += '<div class="painel"><h4>Acesso Rápido</h4><div class="status"><div class="item"><a class="link" href="/login">🔑 Entrar</a></div><div class="item"><a class="link" href="/registro">📝 Criar conta</a></div><div class="item"><a class="link" href="/cadastrar-empresa">🏢 Cadastrar Empresa</a></div><div class="item"><a class="link" href="/cadastrar-vaga">💼 Publicar Vaga</a></div><div class="item"><a class="link" href="/api/health">📡 Health Check</a></div></div></div>'
    html += '<script>setInterval(function(){fetch("/api/health").then(function(r){return r.json()}).then(function(d){document.getElementById("conn2").textContent=d.conexoes_ativas+"/"+d.conexoes_maximas}).catch(function(){})},3000);</script>'
    return pagina(html, 'dashboard')

@app.route('/pcs')
def pcs():
    trilhas = Trilha.query.all()
    niveis = Nivel.query.order_by(Nivel.trilha_id, Nivel.ordem).all()
    html = '<h1>Plano de Cargos e Salários <span>// PCS</span></h1><p class="sub">' + str(len(trilhas)) + ' trilhas • ' + str(len(niveis)) + ' níveis • faixas salariais dinâmicas</p><div class="grade">'
    for t in trilhas:
        qtd = Nivel.query.filter_by(trilha_id=t.id).count()
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:#a855f722">🧭</div><h3>' + t.nome + '</h3><p>' + t.descricao + '</p><p style="margin-top:8px;color:#a855f7;font-weight:600">' + str(qtd) + ' níveis</p></div>'
    html += '</div><div class="painel"><h4>Matriz de Níveis e Faixas Salariais</h4><table class="tabela"><thead><tr><th>Código</th><th>Nível</th><th>Trilha</th><th>Autonomia</th><th>Impacto</th><th>Faixa Salarial</th><th>Posição na faixa</th></tr></thead><tbody>'
    for n in niveis:
        tr = Trilha.query.get(n.trilha_id)
        meio = (n.salario_min + n.salario_max) / 2
        pct = int(((meio - n.salario_min) / (n.salario_max - n.salario_min)) * 100) if n.salario_max > n.salario_min else 50
        html += '<tr><td><b>' + n.codigo + '</b></td><td>' + n.nome + '</td><td>' + (tr.nome if tr else '-') + '</td><td>' + n.autonomia + '</td><td>' + n.impacto + '</td><td>' + fmt(n.salario_min) + ' – ' + fmt(n.salario_max) + '</td><td><div class="barra"><span style="width:' + str(pct) + '%"></span></div></td></tr>'
    html += '</tbody></table></div>'
    return pagina(html, 'pcs')

@app.route('/vagas')
def vagas():
    lista = Vaga.query.all()
    html = '<p style="text-align:right;margin-bottom:12px"><a class="link" href="/cadastrar-vaga">➕ Nova Vaga</a></p><h1>Vagas <span>// Oportunidades</span></h1><p class="sub">' + str(len(lista)) + ' vagas abertas no ecossistema</p><div class="grade">'
    for v in lista:
        cor = ['#3b82f6','#10b981','#f59e0b','#a855f7','#22d3ee'][v.id % 5]
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:' + cor + '22">💼</div><h3>' + v.titulo + '</h3><p>' + v.descricao + '</p><p style="margin-top:8px;color:#8fa3c0;font-size:12px">🏢 ' + v.empresa + ' • Nível <b>' + v.nivel_codigo + '</b></p><p style="margin-top:8px"><span class="pill aberta">' + v.status + '</span></p><p style="margin-top:10px"><a class="link" href="/vagas/' + str(v.id) + '/candidatar">📩 Candidatar-se</a></p></div>'
    html += '</div>'
    return pagina(html, 'vagas')

@app.route('/trilhas')
def trilhas():
    lista = Trilha.query.all()
    html = '<h1>Trilhas de Carreira <span>// Estrutura</span></h1><p class="sub">Caminhos de desenvolvimento profissional</p><div class="grade">'
    for t in lista:
        niveis = Nivel.query.filter_by(trilha_id=t.id).order_by(Nivel.ordem).all()
        nomes = ' → '.join([n.nome for n in niveis])
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:#3b82f622">🧭</div><h3>' + t.nome + '</h3><p>' + t.descricao + '</p><p style="margin-top:10px;font-size:12px;color:#22d3ee">' + nomes + '</p></div>'
    html += '</div>'
    return pagina(html, 'trilhas')

@app.route('/conectividade')
def conectividade():
    html = '<h1>Conectividade <span>// Comunicação Unificada</span></h1><p class="sub">Videoconferência, WhatsApp Business, e-mail corporativo, chat e notificações</p><div class="grade">'
    mods = [
        ('🎥','Videoconferência','Salas com até 5 participantes. WebRTC + Jitsi. Transcrição com IA.','#22d3ee'),
        ('💬','WhatsApp Business','Chatbot de triagem, templates de convite, lembretes automáticos.','#10b981'),
        ('📧','E-mail Corporativo','Templates para todo o ciclo: candidatura → oferta → onboarding.','#3b82f6'),
        ('💭','Chat em Tempo Real','Mensagens instantâneas, arquivos, grupos por vaga. WebSocket.','#a855f7'),
        ('🔔','Notificações Push','Multicanal: push, e-mail, WhatsApp. Preferências por usuário.','#f59e0b'),
        ('📅','Agenda Inteligente','Sugestão de horários, detecção de fuso, lembretes 24h/1h.','#ef4444'),
    ]
    for icone, titulo, desc, cor in mods:
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:' + cor + '22">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p><p style="margin-top:8px"><span class="pill disp">Integrado</span></p></div>'
    html += '</div><div class="painel"><h4>Agentes de Comunicação</h4><div class="status">'
    agentes = ['Agente Convite','Agente Lembrete','Agente Feedback','Agente Onboarding','Agente Pesquisa']
    for a in agentes:
        html += '<div class="item"><span class="dot"></span> ' + a + '</div>'
    html += '</div></div>'
    return pagina(html, 'conect')

@app.route('/candidatos')
def candidatos():
    lista = Usuario.query.filter_by(tipo='candidato').all()
    html = '<h1>Candidatos <span>// Talentos</span></h1><p class="sub">' + str(len(lista)) + ' profissionais no ecossistema</p><div class="painel"><table class="tabela"><thead><tr><th>Nome</th><th>E-mail</th><th>Status</th></tr></thead><tbody>'
    for u in lista:
        html += '<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td><span class="pill disp">Ativo</span></td></tr>'
    html += '</tbody></table></div>'
    return pagina(html, 'cand')

@app.route('/empresas')
def empresas():
    lista = Usuario.query.filter_by(tipo='empresa').all()
    html = '<p style="text-align:right;margin-bottom:12px"><a class="link" href="/cadastrar-empresa">➕ Cadastrar Empresa</a></p><h1>Empresas <span>// Contratantes</span></h1><p class="sub">' + str(len(lista)) + ' organizações no ecossistema</p><div class="painel"><table class="tabela"><thead><tr><th>Razão Social</th><th>E-mail</th><th>Setor</th><th>Status</th></tr></thead><tbody>'
    for u in lista:
        html += '<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td>' + (Empresa.query.filter_by(usuario_id=u.id).first().setor if Empresa.query.filter_by(usuario_id=u.id).first() else '-') + '</td><td><span class="pill aberta">Verificada</span></td></tr>'
    html += '</tbody></table></div>'
    return pagina(html, 'emp')

@app.route('/agentes')
def agentes():
    agentes = [
        ('🤖','Agente Sourcing','Busca candidatos em múltiplas fontes 24/7','#3b82f6'),
        ('🧪','Agente Triagem','Avalia currículos com NLP e ranqueia','#10b981'),
        ('📅','Agente Scheduling','Negocia horários de entrevista','#f59e0b'),
        ('📩','Agente Follow-up','Mantém candidatos engajados','#a855f7'),
        ('⚖️','Agente DEI','Monitora equidade e diversidade do pipeline','#22d3ee'),
    ]
    html = '<h1>IA e Automação <span>// Agentes Autônomos</span></h1><p class="sub">5 agentes especializados trabalhando em tempo real</p><div class="grade">'
    for icone, nome, desc, cor in agentes:
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:' + cor + '22">' + icone + '</div><h3>' + nome + '</h3><p>' + desc + '</p><p style="margin-top:8px"><span class="pill aberta">● Ativo</span></p></div>'
    html += '</div>'
    return pagina(html, 'agent')

@app.route('/login')
def login_page():
    html = '<h1>Entrar <span>// Autenticação</span></h1><p class="sub">Use as credenciais de teste ou crie uma conta</p><div class="painel"><form id="f"><label>E-mail</label><input id="em" placeholder="ex: candidato@teste.com"><label>Senha</label><input id="se" type="password" placeholder="••••••••"><button type="submit">Entrar</button></form><div id="msg" style="margin-top:14px"></div><p style="margin-top:16px;font-size:12px;color:#8fa3c0">Teste: candidato@teste.com / candidato123 • empresa@teste.com / empresa123 • admin@rh.com / admin123</p></div><script>document.getElementById("f").onsubmit=function(e){e.preventDefault();fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:document.getElementById("em").value,senha:document.getElementById("se").value})}).then(function(r){return r.json()}).then(function(d){if(d.ok){document.getElementById("msg").innerHTML="<div class=aviso>✅ Bem-vindo(a), "+d.usuario.nome+"! ("+d.usuario.tipo+")</div>"}else{document.getElementById("msg").innerHTML="<div class=erro>❌ "+d.erro+"</div>"}})};</script>'
    return pagina(html, 'login')

@app.route('/registro')
def registro_page():
    html = '<h1>Criar Conta <span>// Novo usuário</span></h1><p class="sub">Registre-se como candidato ou empresa</p><div class="painel"><form id="f"><label>Nome</label><input id="no" placeholder="Seu nome ou razão social"><label>E-mail</label><input id="em" placeholder="voce@email.com"><label>Senha</label><input id="se" type="password"><label>Tipo</label><select id="ti"><option value="candidato">Candidato</option><option value="empresa">Empresa</option></select><button type="submit">Criar conta</button></form><div id="msg" style="margin-top:14px"></div></div><script>document.getElementById("f").onsubmit=function(e){e.preventDefault();fetch("/api/registro",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({nome:document.getElementById("no").value,email:document.getElementById("em").value,senha:document.getElementById("se").value,tipo:document.getElementById("ti").value})}).then(function(r){return r.json()}).then(function(d){if(d.ok){document.getElementById("msg").innerHTML="<div class=aviso>✅ Conta criada! Faça login.</div>"}else{document.getElementById("msg").innerHTML="<div class=erro>❌ "+d.erro+"</div>"}})};</script>'
    return pagina(html, 'login')


# ============ CADASTRO DE EMPRESA ============
@app.route('/cadastrar-empresa')
def pagina_cadastrar_empresa():
    html = '<p><a class="link" href="/empresas">← Voltar para empresas</a></p><h1>Cadastrar Empresa <span>// Perfil completo</span></h1><p class="sub">Ativa o módulo Empresas com employer branding, talent pool e ATS</p><div class="painel"><form id="f">'
    html += '<label>Razão Social *</label><input id="ra" required placeholder="Razão social completa da empresa">'
    html += '<label>Nome Fantasia</label><input id="nf" placeholder="Nome pelo qual é conhecida">'
    html += '<label>CNPJ *</label><input id="cn" required placeholder="00.000.000/0000-00">'
    html += '<label>Porte</label><select id="po"><option>ME</option><option>EPP</option><option>Médio</option><option>Grande</option></select>'
    html += '<label>Setor</label><input id="se" placeholder="ex: Tecnologia, RH, Varejo">'
    html += '<label>E-mail corporativo *</label><input id="em" type="email" required placeholder="contato@empresa.com">'
    html += '<label>Descrição</label><textarea id="de" rows="3" style="padding:11px 14px;background:#0d1b30;border:1px solid #1c2f4a;border-radius:8px;color:#fff;font-size:14px;font-family:inherit" placeholder="O que a empresa faz?"></textarea>'
    html += '<label>Cultura e Valores</label><textarea id="cu" rows="3" style="padding:11px 14px;background:#0d1b30;border:1px solid #1c2f4a;border-radius:8px;color:#fff;font-size:14px;font-family:inherit" placeholder="Missão, valores, clima..."></textarea>'
    html += '<button type="submit">🏢 Cadastrar empresa</button>'
    html += '</form><div id="msg" style="margin-top:14px"></div></div>'
    html += '<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();var b=document.querySelector("button[type=submit]");b.disabled=true;b.textContent="⏳ Salvando...";'
    html += 'fetch("/api/empresas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({razao_social:document.getElementById("ra").value,nome_fantasia:document.getElementById("nf").value,cnpj:document.getElementById("cn").value,porte:document.getElementById("po").value,setor:document.getElementById("se").value,email:document.getElementById("em").value,descricao:document.getElementById("de").value,cultura:document.getElementById("cu").value})})'
    html += '.then(function(r){return r.json()}).then(function(d){if(d.ok){document.getElementById("msg").innerHTML="<div class=aviso>✅ Empresa cadastrada! ID: "+d.empresa_id+"</div>";document.getElementById("f").style.display="none";}else{document.getElementById("msg").innerHTML="<div class=erro>❌ "+d.erro+"</div>";b.disabled=false;b.textContent="🏢 Cadastrar empresa";}})'
    html += '.catch(function(){document.getElementById("msg").innerHTML="<div class=erro>❌ Erro de conexão</div>";b.disabled=false;b.textContent="🏢 Cadastrar empresa";})};</script>'
    return pagina(html, 'emp')

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
        u = Usuario(nome=razao, email=email, senha_hash=generate_password_hash('empresa123'), tipo='empresa', ativo=True)
        db.session.add(u); db.session.flush()
    emp = Empresa(usuario_id=u.id, razao_social=razao, nome_fantasia=d.get('nome_fantasia'), cnpj=cnpj, porte=d.get('porte'), setor=d.get('setor'), descricao=d.get('descricao'), cultura=d.get('cultura'))
    db.session.add(emp); db.session.commit()
    return jsonify({'ok': True, 'empresa_id': emp.id, 'razao_social': emp.razao_social})

# ============ CADASTRO DE VAGA ============
@app.route('/cadastrar-vaga')
def pagina_cadastrar_vaga():
    html = '<p><a class="link" href="/vagas">← Voltar para vagas</a></p><h1>Cadastrar Vaga <span>// Nova oportunidade</span></h1><p class="sub">Publique uma vaga e o Agente Sourcing busca talentos automaticamente</p><div class="painel"><form id="f">'
    html += '<label>Título da vaga *</label><input id="ti" required placeholder="ex: Desenvolvedor(a) Python Pleno">'
    html += '<label>Empresa *</label><select id="em" required><option value="">Selecione...</option>'
    for e in Empresa.query.all():
        html += '<option value="' + e.razao_social + '">' + e.razao_social + '</option>'
    html += '</select>'
    html += '<label>Nível (PCS) *</label><select id="nv" required><option value="">Selecione...</option>'
    for n in Nivel.query.order_by(Nivel.ordem).all():
        html += '<option value="' + n.codigo + '">' + n.nome + ' (' + n.codigo + ')</option>'
    html += '</select>'
    html += '<label>Descrição</label><textarea id="de" rows="4" style="padding:11px 14px;background:#0d1b30;border:1px solid #1c2f4a;border-radius:8px;color:#fff;font-size:14px;font-family:inherit" placeholder="Descrição da vaga, responsabilidades, requisitos..."></textarea>'
    html += '<div class="duo"><div><label>Salário mínimo (R$)</label><input id="smin" type="number" min="0" step="100"></div><div><label>Salário máximo (R$)</label><input id="smax" type="number" min="0" step="100"></div></div>'
    html += '<label>Regime</label><select id="re"><option value="remoto">Remoto</option><option value="hibrido">Híbrido</option><option value="presencial">Presencial</option></select>'
    html += '<label>Localização</label><input id="lo" placeholder="ex: São Paulo/SP, ou Remoto">'
    html += '<button type="submit">💼 Publicar vaga</button>'
    html += '</form><div id="msg" style="margin-top:14px"></div></div>'
    html += '<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();var b=document.querySelector("button[type=submit]");b.disabled=true;b.textContent="⏳ Publicando...";'
    html += 'fetch("/api/vagas/cadastrar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({titulo:document.getElementById("ti").value,empresa:document.getElementById("em").value,nivel_codigo:document.getElementById("nv").value,descricao:document.getElementById("de").value,salario_min:parseFloat(document.getElementById("smin").value)||0,salario_max:parseFloat(document.getElementById("smax").value)||0,regime:document.getElementById("re").value,localizacao:document.getElementById("lo").value})})'
    html += '.then(function(r){return r.json()}).then(function(d){if(d.ok){document.getElementById("msg").innerHTML="<div class=aviso>✅ Vaga publicada! <a class=link href=/vagas>Ver vagas</a></div>";document.getElementById("f").style.display="none";}else{document.getElementById("msg").innerHTML="<div class=erro>❌ "+d.erro+"</div>";b.disabled=false;b.textContent="💼 Publicar vaga";}})'
    html += '.catch(function(){document.getElementById("msg").innerHTML="<div class=erro>❌ Erro de conexão</div>";b.disabled=false;b.textContent="💼 Publicar vaga";})};</script>'
    return pagina(html, 'vagas')

@app.route('/api/vagas/cadastrar', methods=['POST'])
def api_cadastrar_vaga():
    d = request.get_json(force=True)
    titulo = (d.get('titulo') or '').strip()
    empresa = (d.get('empresa') or '').strip()
    nivel = (d.get('nivel_codigo') or '').strip()
    if not titulo or not empresa or not nivel:
        return jsonify({'erro': 'Preencha título, empresa e nível'}), 400
    v = Vaga(titulo=titulo, descricao=d.get('descricao'), empresa=empresa, nivel_codigo=nivel, status='aberta',
             salario_min=d.get('salario_min') or None, salario_max=d.get('salario_max') or None,
             regime=d.get('regime'), localizacao=d.get('localizacao'))
    db.session.add(v); db.session.commit()
    return jsonify({'ok': True, 'vaga_id': v.id, 'titulo': v.titulo, 'status': 'aberta'})

# ============ API JSON ============
@app.route('/api/health')
def health():
    return jsonify({'status':'online','versao':'2.0.0','conexoes_ativas':conexoes_ativas,'conexoes_maximas':MAX_CONEXOES,'modulos':['usuarios','vagas','candidatos','empresas','pcs','conectividade','recrutamento','analytics','experiencia','inovacao'],'agentes':['sourcing','triagem','scheduling','followup','dei'],'trilhas':Trilha.query.count(),'niveis':Nivel.query.count(),'vagas':Vaga.query.count()})

@app.route('/api/trilhas')
def api_trilhas():
    return jsonify([{'id':t.id,'nome':t.nome,'descricao':t.descricao} for t in Trilha.query.all()])

@app.route('/api/niveis')
def api_niveis():
    return jsonify([{'id':n.id,'codigo':n.codigo,'nome':n.nome,'ordem':n.ordem,'salario_min':n.salario_min,'salario_max':n.salario_max,'autonomia':n.autonomia,'impacto':n.impacto,'trilha_id':n.trilha_id} for n in Nivel.query.order_by(Nivel.ordem).all()])

@app.route('/api/vagas')
def api_vagas():
    return jsonify([{'id':v.id,'titulo':v.titulo,'empresa':v.empresa,'nivel_codigo':v.nivel_codigo,'status':v.status} for v in Vaga.query.all()])

@app.route('/vagas/<int:vid>/candidatar')
def form_candidatura(vid):
    v = Vaga.query.get(vid)
    if not v:
        return pagina('<h1>Vaga não encontrada</h1>', 'vagas')
    html = '<p><a class="link" href="/vagas">← Voltar para vagas</a></p>'
    html += '<h1>Candidatar-se <span>// ' + v.titulo + '</span></h1>'
    html += '<p class="sub">🏢 ' + v.empresa + ' • Nível <b>' + v.nivel_codigo + '</b> • Vaga #' + str(v.id) + '</p>'
    html += '<div class="painel"><form id="f">'
    html += '<label>Nome completo *</label><input id="no" placeholder="Seu nome completo" required>'
    html += '<label>E-mail *</label><input id="em" type="email" placeholder="voce@email.com" required>'
    html += '<label>Telefone / WhatsApp</label><input id="te" placeholder="(00) 00000-0000">'
    html += '<label>Pretensão salarial (R$)</label><input id="sa" type="number" min="0" step="500" placeholder="ex: 9000">'
    html += '<label>Disponibilidade</label><select id="di"><option value="imediata">Imediata</option><option value="15dias">Em até 15 dias</option><option value="30dias">Em até 30 dias</option><option value="60dias">Em até 60 dias</option></select>'
    html += '<label>Por que você é a pessoa certa?</label><textarea id="me" rows="4" style="padding:11px 14px;background:#0d1b30;border:1px solid #1c2f4a;border-radius:8px;color:#fff;font-size:14px;font-family:inherit" placeholder="Conte um pouco sobre você, suas experiências e o que pode entregar..."></textarea>'
    html += '<button type="submit">📩 Enviar candidatura</button>'
    html += '</form><div id="msg" style="margin-top:14px"></div></div>'
    html += '<script>'
    html += 'document.getElementById("f").onsubmit=function(e){e.preventDefault();'
    html += 'var b=document.querySelector("button[type=submit]");b.disabled=true;b.textContent="⏳ Enviando...";'
    html += 'fetch("/api/vagas/' + str(vid) + '/candidatar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({'
    html += 'nome:document.getElementById("no").value,email:document.getElementById("em").value,'
    html += 'telefone:document.getElementById("te").value,salario:parseFloat(document.getElementById("sa").value)||0,'
    html += 'disponibilidade:document.getElementById("di").value,mensagem:document.getElementById("me").value'
    html += '})}).then(function(r){return r.json()}).then(function(d){'
    html += 'if(d.ok){document.getElementById("msg").innerHTML="<div class=aviso>✅ Candidatura enviada com sucesso!<br><b>Match Score: " + d.match_score + "%</b> • Status: " + d.status + "</div>";'
    html += 'document.getElementById("f").style.display="none";'
    html += '}else{document.getElementById("msg").innerHTML="<div class=erro>❌ " + d.erro + "</div>";b.disabled=false;b.textContent="📩 Enviar candidatura";}})'
    html += '.catch(function(){document.getElementById("msg").innerHTML="<div class=erro>❌ Erro de conexão. Tente novamente.</div>";b.disabled=false;b.textContent="📩 Enviar candidatura";})};'
    html += '</script>'
    return pagina(html, 'vagas')

@app.route('/api/vagas/<int:vid>/candidatar', methods=['POST'])
def candidatar(vid):
    v = Vaga.query.get(vid)
    if not v:
        return jsonify({'erro':'Vaga não encontrada'}), 404
    d = request.get_json(force=True)
    nome = (d.get('nome') or '').strip()
    email = (d.get('email') or '').strip()
    if not nome or not email:
        return jsonify({'erro':'Preencha nome e e-mail'}), 400
    cand = Usuario.query.filter_by(email=email).first()
    if not cand:
        cand = Usuario(nome=nome, email=email, senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True)
        db.session.add(cand); db.session.flush()
    else:
        cand.nome = nome
    score = random.randint(62, 97)
    c = Candidatura(vaga_id=vid, candidato_id=cand.id, match_score=score, status='pendente')
    db.session.add(c); db.session.commit()
    return jsonify({'ok':True,'vaga':v.titulo,'empresa':v.empresa,'candidato':cand.nome,'email':email,'match_score':score,'status':'pendente'})

@app.route('/api/registro', methods=['POST'])
def api_registro():
    d = request.get_json(force=True)
    if not d.get('nome') or not d.get('email') or not d.get('senha'):
        return jsonify({'erro':'Preencha nome, email e senha'}), 400
    if Usuario.query.filter_by(email=d['email']).first():
        return jsonify({'erro':'Email já cadastrado'}), 409
    u = Usuario(nome=d['nome'], email=d['email'], senha_hash=generate_password_hash(d['senha']), tipo=d.get('tipo','candidato'), ativo=True)
    db.session.add(u); db.session.commit()
    return jsonify({'ok':True,'usuario':{'id':u.id,'nome':u.nome,'email':u.email,'tipo':u.tipo}}), 201

@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.get_json(force=True)
    u = Usuario.query.filter_by(email=d.get('email')).first()
    if not u or not check_password_hash(u.senha_hash, d.get('senha')):
        return jsonify({'erro':'Credenciais inválidas'}), 401
    return jsonify({'ok':True,'usuario':{'id':u.id,'nome':u.nome,'email':u.email,'tipo':u.tipo}})

# ============ INICIO ============
with app.app_context():
    db.create_all()
    criar_dados_iniciais()

if __name__ == '__main__':
    print()
    print('=' * 58)
    print('  🌐 ECOSSISTEMA DE RH INOVADOR v2.0')
    print('  🚀 Interface visual completa!')
    print('=' * 58)
    print('  🖥️  Menu principal: http://localhost:5000/')
    print('  📊 PCS:            http://localhost:5000/pcs')
    print('  💼 Vagas:          http://localhost:5000/vagas')
    print('  🧭 Trilhas:        http://localhost:5000/trilhas')
    print('  📡 Conectividade:  http://localhost:5000/conectividade')
    print('  👤 Candidatos:     http://localhost:5000/candidatos')
    print('  🏢 Empresas:       http://localhost:5000/empresas')
    print('  🤖 Agentes:        http://localhost:5000/agentes')
    print('  🔌 Conexões em tempo real: máx 5')
    print('=' * 58)
    print('  Pressione CTRL+C para parar')
    print()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
