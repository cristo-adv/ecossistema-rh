# -*- coding: utf-8 -*-
"""Ecossistema de RH Inovador v3.0 — turbo: login, paineis, candidaturas reais."""

import os
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

# ================= MODELOS =================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    ativo = db.Column(db.Boolean, default=True)

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

class Candidatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vaga_id = db.Column(db.Integer, db.ForeignKey('vaga.id'))
    candidato_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    match_score = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pendente')
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

# ================= SEED =================
def criar_dados_iniciais():
    if Usuario.query.first():
        return
    admin = Usuario(nome='Administrador', email='admin@rh.com',
                    senha_hash=generate_password_hash('admin123'), tipo='admin', ativo=True)
    cand = Usuario(nome='Maria Silva', email='candidato@teste.com',
                   senha_hash=generate_password_hash('candidato123'), tipo='candidato', ativo=True)
    emp = Usuario(nome='RH Inovador S.A.', email='empresa@teste.com',
                  senha_hash=generate_password_hash('empresa123'), tipo='empresa', ativo=True)
    db.session.add_all([admin, cand, emp])
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
        ('/painel', '🔑', 'Meu Painel'),
    ]
    itens = ''
    for href, icone, nome in nav:
        cls = ' class="ativo"' if href == ativo else ''
        itens += '<a href="' + href + '"' + cls + '>' + icone + ' ' + nome + '</a>'
    if u:
        chip = ('<div class="chip"><span class="pill ' + u.tipo + '">' + u.tipo + '</span> '
                '<b>' + u.nome + '</b> '
                '<a class="link" href="/painel">Meu Painel</a> | '
                '<a class="link" href="/logout">Sair</a></div>')
    else:
        chip = ('<div class="chip"><a class="btn" href="/login">🔑 Entrar</a> '
                '<a class="btn cinza" href="/registro">📝 Criar conta</a></div>')
    base = '''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ecossistema RH Inovador</title><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
body{background:#0a1628;color:#e5eaf3;display:flex;min-height:100vh}
aside{width:240px;background:#0d1b30;border-right:1px solid #1c2f4a;padding:20px 14px;flex-shrink:0}
aside h2{font-size:14px;color:#3b82f6;margin-bottom:20px;letter-spacing:.5px}
aside nav a{display:block;padding:9px 12px;border-radius:8px;color:#9fb0c8;text-decoration:none;font-size:13px;margin-bottom:3px;transition:.2s}
aside nav a:hover{background:#16283f;color:#fff}
aside nav a.ativo{background:#1d4ed8;color:#fff}
main{flex:1;padding:26px 32px;overflow-y:auto}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}
header h1{font-size:22px}header h1 span{color:#3b82f6}
.chip{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px}
.btn{background:#1d4ed8;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;font-size:13px;border:none;cursor:pointer}
.btn.cinza{background:#1e293b}.btn:hover{opacity:.9}
.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-bottom:24px}
.card{background:linear-gradient(145deg,#0f2140,#0d1b30);border:1px solid #1c2f4a;border-radius:14px;padding:20px;transition:.25s}
.card:hover{border-color:#3b82f6;transform:translateY(-3px)}
.card .icone{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;margin-bottom:12px}
.card h3{font-size:15px;margin-bottom:6px}.card p{font-size:12px;color:#8fa3c0;line-height:1.5}
.painel{background:#0d1b30;border:1px solid #1c2f4a;border-radius:14px;padding:20px 24px;margin-bottom:20px}
.painel h4{font-size:12px;color:#8fa3c0;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}
.status{display:flex;flex-wrap:wrap;gap:18px;font-size:14px}
.item{display:flex;align-items:center;gap:9px}
.dot{width:10px;height:10px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981}
.dot.roxo{background:#a855f7;box-shadow:0 0 8px #a855f7}
.dot.ciano{background:#22d3ee;box-shadow:0 0 8px #22d3ee}
.tabela{width:100%;border-collapse:collapse;font-size:13px}
.tabela th{text-align:left;color:#8fa3c0;padding:10px;border-bottom:1px solid #1c2f4a;text-transform:uppercase;font-size:11px;letter-spacing:.5px}
.tabela td{padding:10px;border-bottom:1px solid #16283f}
.tabela tr:hover td{background:#0f2140}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px}
.pill.aberta,.pill.candidato{background:#10b98122;color:#10b981}
.pill.fechada{background:#ef444422;color:#ef4444}
.pill.empresa{background:#f59e0b22;color:#f59e0b}
.pill.admin{background:#a855f722;color:#a855f7}
.pill.pendente{background:#f59e0b22;color:#f59e0b}
form label{display:block;margin:12px 0 5px;font-size:13px;color:#9fb0c8}
form input,form select,form textarea{width:100%;background:#0a1628;border:1px solid #1c2f4a;border-radius:8px;padding:10px 12px;color:#fff;font-size:14px}
form input:focus,form select:focus,form textarea:focus{outline:none;border-color:#3b82f6}
.mensagem{display:none;margin-top:14px;padding:12px;border-radius:8px;font-size:13px}
.mensagem.ok{display:block;background:#10b98122;color:#10b981}
.mensagem.erro{display:block;background:#ef444422;color:#ef4444}
.link{color:#3b82f6;text-decoration:none}
.sub{color:#8fa3c0;font-size:13px;margin-bottom:18px}
footer{margin-top:24px;color:#475569;font-size:12px}
@media(max-width:800px){body{flex-direction:column}aside{width:100%;border-right:none;border-bottom:1px solid #1c2f4a}main{padding:18px}}
</style></head><body>
<aside><h2>⚡ ECOSSISTEMA RH</h2><nav>@NAV@</nav></aside>
<main><header><h1>Ecossistema RH <span>// Inovador</span></h1>@CHIP@</header>
@CONTEUDO@
<footer>Ecossistema de RH Inovador v3.0 — dados permanentes | conexões em tempo real: <span id="conn">0/@MAX@</span></footer>
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

def pagina_form(titulo, campos, acao, botao='Salvar'):
    h = '<h1>' + titulo + '</h1><div class="painel" style="max-width:560px"><form id="f">'
    for nome, label, tipo in campos:
        h += '<label>' + label + '</label>'
        if tipo == 'select' and nome == 'tipo':
            h += ('<select id="tipo"><option value="candidato">Candidato(a) — procuro emprego</option>'
                  '<option value="empresa">Empresa — quero contratar</option></select>')
        elif tipo == 'select':
            h += '<select id="' + nome + '"><option value="">Selecione...</option>'
            if nome == 'nivel_codigo':
                for n in Nivel.query.order_by(Nivel.ordem).all():
                    h += '<option value="' + n.codigo + '">' + n.nome + ' (' + n.codigo + ')</option>'
            elif nome == 'empresa':
                for e in Empresa.query.all():
                    h += '<option value="' + e.razao_social + '">' + e.razao_social + '</option>'
            h += '</select>'
        else:
            h += '<input id="' + nome + '" type="' + tipo + '" placeholder="' + label + '" required>'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">' + botao + '</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();var d={};'
          '["' + '","'.join(c[0] for c in campos) + '"].forEach(function(k){var el=document.getElementById(k);if(el)d[k]=el.value;});'
          'fetch("' + acao + '",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");'
          'if(res.ok){m.className="mensagem ok";m.innerHTML="✅ "+(res.j.msg||"Salvo com sucesso!")+" <a class=link href=/painel>Ir para Meu Painel</a>";}'
          'else{m.className="mensagem erro";m.innerHTML="❌ "+(res.j.erro||"Erro");}});};</script>')
    return pagina(h, '/painel' if 'painel' in acao else '')

# ================= AUTH (PAGINAS) =================
@app.route('/registro')
def registro():
    h = '<h1>Criar Conta <span>// Comece agora</span></h1><div class="painel" style="max-width:560px"><form id="f" method="post" action="/registro">'
    h += '<label>Nome completo</label><input name="nome" required placeholder="Seu nome">'
    h += '<label>E-mail</label><input name="email" type="email" required placeholder="voce@email.com">'
    h += '<label>Senha</label><input name="senha" type="password" required placeholder="Mínimo 6 caracteres">'
    h += '<label>Tipo de conta</label><select name="tipo"><option value="candidato">Candidato(a) — procuro emprego</option><option value="empresa">Empresa — quero contratar</option></select>'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Criar conta</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();var f=this;'
          'fetch("/api/registro",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({nome:f.nome.value,email:f.email.value,senha:f.senha.value,tipo:f.tipo.value})})'
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

# ================= MEU PAINEL =================
@app.route('/painel')
@login_required
def painel():
    u = usuario_atual()
    h = '<h1>Meu Painel <span>// ' + u.nome + '</span></h1><p class="sub">Acompanhe suas atividades no ecossistema.</p>'
    if u.tipo == 'candidato':
        cands = Candidatura.query.filter_by(candidato_id=u.id).order_by(Candidatura.id.desc()).all()
        h += '<div class="painel"><h4>Minhas Candidaturas</h4>'
        if cands:
            h += '<table class="tabela"><thead><tr><th>Vaga</th><th>Empresa</th><th>Match Score</th><th>Status</th><th>Data</th></tr></thead><tbody>'
            for c in cands:
                v = Vaga.query.get(c.vaga_id)
                h += ('<tr><td><b>' + (v.titulo if v else 'Vaga') + '</b></td><td>' + (v.empresa if v else '-') + '</td>'
                      '<td><b style="color:#22d3ee">' + str(int(c.match_score)) + '%</b></td>'
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
            h += '<table class="tabela"><thead><tr><th>Vaga</th><th>Nível</th><th>Candidaturas</th><th>Status</th></tr></thead><tbody>'
            for v in vagas:
                total = Candidatura.query.filter_by(vaga_id=v.id).count()
                h += ('<tr><td><b>' + v.titulo + '</b></td><td>' + (v.nivel_codigo or '-') + '</td>'
                      '<td><a class="link" href="/candidatos">' + str(total) + '</a></td>'
                      '<td><span class="pill ' + v.status + '">' + v.status + '</span></td></tr>')
            h += '</tbody></table>'
        else:
            h += '<p style="color:#8fa3c0">Nenhuma vaga publicada. <a class="link" href="/cadastrar-vaga">Publicar vaga →</a></p>'
        h += '</div>'
    else:
        h += '<div class="painel"><h4>Visão Geral (Administrador)</h4><div class="status">'
        h += '<div class="item"><span class="dot"></span> Candidatos: <b>' + str(Usuario.query.filter_by(tipo='candidato').count()) + '</b></div>'
        h += '<div class="item"><span class="dot ciano"></span> Empresas: <b>' + str(Usuario.query.filter_by(tipo='empresa').count()) + '</b></div>'
        h += '<div class="item"><span class="dot roxo"></span> Vagas: <b>' + str(Vaga.query.count()) + '</b></div>'
        h += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(Candidatura.query.count()) + '</b></div>'
        h += '</div></div>'
        h += '<div class="painel"><h4>Atalhos</h4><div class="status">'
        h += '<a class="btn" href="/cadastrar-vaga">➕ Publicar Vaga</a> <a class="btn cinza" href="/cadastrar-empresa">🏢 Cadastrar Empresa</a> <a class="btn cinza" href="/analytics">📈 Analytics</a>'
        h += '</div></div>'
    return pagina(h, '/painel')

# ================= PAGINAS PUBLICAS =================
@app.route('/')
def menu():
    cards = [
        ('🧠', 'Recrutamento Inteligente', 'IA generativa, matching preditivo e triagem NLP', '#3b82f6', '/recrutamento'),
        ('👤', 'Candidatos', 'Perfil blockchain, gamificação e match score', '#10b981', '/candidatos'),
        ('🏢', 'Empresas', 'ATS inteligente, employer branding e talent pool', '#f59e0b', '/empresas'),
        ('📊', 'Plano de Cargos e Salários', 'Níveis Júnior a Fellow, faixas e promoções', '#a855f7', '/pcs'),
        ('📡', 'Conectividade', 'Vídeo, WhatsApp, e-mail e chat em tempo real', '#22d3ee', '/conectividade'),
        ('💼', 'Vagas', 'Oportunidades abertas e candidaturas', '#ef4444', '/vagas'),
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
    h += '<div class="item"><span class="dot"></span> Módulos: <b>10</b></div>'
    h += '</div></div>'
    h += '<script>setInterval(function(){fetch("/api/health").then(function(r){return r.json();}).then(function(d){'
    h += 'var el=document.getElementById("conn2");if(el)el.textContent=d.conexoes_ativas+"/"+d.conexoes_maximas;}).catch(function(){});},3000);</script>'
    return pagina(h, '/')

@app.route('/pcs')
def pcs():
    trilhas = Trilha.query.all()
    niveis = Nivel.query.order_by(Nivel.trilha_id, Nivel.ordem).all()
    h = '<h1>Plano de Cargos e Salários <span>// PCS</span></h1>'
    h += '<p class="sub">' + str(len(trilhas)) + ' trilhas • ' + str(len(niveis)) + ' níveis • faixas salariais dinâmicas</p>'
    for t in trilhas:
        qtd = Nivel.query.filter_by(trilha_id=t.id).count()
        h += '<div class="painel"><h4>🧭 ' + t.nome + ' • ' + str(qtd) + ' níveis</h4><p style="color:#8fa3c0;font-size:13px;margin-bottom:12px">' + (t.descricao or '') + '</p>'
        h += '<table class="tabela"><thead><tr><th>Código</th><th>Nível</th><th>Autonomia</th><th>Impacto</th><th>Faixa Salarial</th></tr></thead><tbody>'
        for n in Nivel.query.filter_by(trilha_id=t.id).order_by(Nivel.ordem).all():
            h += ('<tr><td><b>' + n.codigo + '</b></td><td>' + n.nome + '</td><td>' + (n.autonomia or '-') + '</td>'
                  '<td>' + (n.impacto or '-') + '</td><td><b style="color:#22d3ee">R$ ' + format(int(n.salario_min or 0), ',d').replace(',', '.') + ' – R$ ' + format(int(n.salario_max or 0), ',d').replace(',', '.') + '</b></td></tr>')
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
    lista = Vaga.query.filter_by(status='aberta').order_by(Vaga.id.desc()).all()
    h = '<h1>Vagas <span>// Oportunidades</span></h1>'
    h += '<p class="sub">' + str(len(lista)) + ' vagas abertas no ecossistema</p>'
    h += '<div class="painel"><p><a class="btn cinza" href="/cadastrar-vaga">➕ Nova Vaga</a></p></div>'
    for v in lista:
        h += ('<div class="painel"><div class="status" style="justify-content:space-between;flex-wrap:wrap">'
              '<div><h3>💼 ' + v.titulo + '</h3>'
              '<p style="color:#8fa3c0;font-size:13px;margin-top:6px">' + (v.descricao or '') + '</p>'
              '<p style="color:#8fa3c0;font-size:12px;margin-top:6px">🏢 ' + (v.empresa or '-') + ' • Nível <b>' + (v.nivel_codigo or '-') + '</b> • ' + (v.regime or '-') + ' • ' + (v.localizacao or '-') + '</p></div>'
              '<div style="text-align:right"><span class="pill ' + v.status + '">' + v.status + '</span><br><br>'
              '<a class="btn" href="/vagas/' + str(v.id) + '/candidatar">📩 Candidatar-se</a></div></div></div>')
    return pagina(h, '/vagas')

@app.route('/vagas/<int:vid>/candidatar')
def form_candidatura(vid):
    v = Vaga.query.get(vid)
    if not v:
        return pagina('<h1>Vaga não encontrada</h1>', '/vagas')
    u = usuario_atual()
    nome = u.nome if u else ''
    email = u.email if u else ''
    h = '<h1>Candidatar-se <span>// ' + v.titulo + '</span></h1>'
    h += '<p class="sub">🏢 ' + (v.empresa or '-') + ' • Nível ' + (v.nivel_codigo or '-') + ' • ' + (v.regime or '-') + '</p>'
    h += '<div class="painel" style="max-width:560px"><form id="f">'
    h += '<label>Seu nome</label><input id="nome" required value="' + nome + '" placeholder="Seu nome completo">'
    h += '<label>Seu e-mail</label><input id="email" type="email" required value="' + email + '" placeholder="voce@email.com">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Enviar candidatura</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'fetch("/api/vagas/' + str(vid) + '/candidatar",{method:"POST",headers:{"Content-Type":"application/json"},'
          'body:JSON.stringify({nome:document.getElementById("nome").value,email:document.getElementById("email").value})})'
          '.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})'
          '.then(function(res){var m=document.getElementById("msg");if(res.ok){'
          'm.className="mensagem ok";m.innerHTML="✅ Candidatura enviada! Match Score: <b>"+res.j.match_score+"%</b>";}'
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
    h += '<label>Regime</label><select id="regime"><option value="Remoto">Remoto</option><option value="Híbrido">Híbrido</option><option value="Presencial">Presencial</option></select>'
    h += '<label>Localização</label><input id="localizacao" placeholder="ex: Curitiba/PR">'
    h += '<label>Salário mínimo</label><input id="salario_min" type="number" placeholder="ex: 8000">'
    h += '<label>Salário máximo</label><input id="salario_max" type="number" placeholder="ex: 12000">'
    h += '<div style="margin-top:16px"><button class="btn" type="submit">Publicar vaga</button></div>'
    h += '<div class="mensagem" id="msg"></div></form></div>'
    h += ('<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();'
          'var d={titulo:document.getElementById("titulo").value,empresa:document.getElementById("empresa").value,'
          'nivel_codigo:document.getElementById("nivel_codigo").value,descricao:document.getElementById("descricao").value,'
          'regime:document.getElementById("regime").value,localizacao:document.getElementById("localizacao").value,'
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
    h += '<div class="painel"><table class="tabela"><thead><tr><th>Nome</th><th>E-mail</th><th>Candidaturas</th><th>Status</th></tr></thead><tbody>'
    for u in lista:
        total = Candidatura.query.filter_by(candidato_id=u.id).count()
        h += ('<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td>' + str(total) + '</td>'
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
        h += '<div style="background:#0a1628;border-radius:6px;height:10px;margin-top:4px"><div style="background:#3b82f6;width:' + str(pct) + '%;height:10px;border-radius:6px"></div></div></div>'
    h += '</div>'
    ultimas = Candidatura.query.order_by(Candidatura.id.desc()).limit(10).all()
    if ultimas:
        h += '<div class="painel"><h4>Últimas Candidaturas</h4><table class="tabela"><thead><tr><th>Vaga</th><th>Candidato</th><th>Match</th><th>Status</th></tr></thead><tbody>'
        for c in ultimas:
            v = Vaga.query.get(c.vaga_id)
            u = Usuario.query.get(c.candidato_id)
            h += ('<tr><td>' + (v.titulo if v else '-') + '</td><td>' + (u.nome if u else '-') + '</td>'
                  '<td><b style="color:#22d3ee">' + str(int(c.match_score or 0)) + '%</b></td>'
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

# ================= API JSON =================
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'online', 'versao': '3.0.0',
        'conexoes_ativas': conexoes_ativas, 'conexoes_maximas': MAX_CONEXOES,
        'modulos': ['usuarios', 'vagas', 'candidatos', 'empresas', 'pcs', 'conectividade',
                    'recrutamento', 'analytics', 'experiencia', 'inovacao'],
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
                     'regime': v.regime, 'localizacao': v.localizacao}
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

@app.route('/api/vagas/cadastrar', methods=['POST'])
def api_cadastrar_vaga():
    d = request.get_json(force=True)
    titulo = (d.get('titulo') or '').strip()
    empresa = (d.get('empresa') or '').strip()
    nivel = (d.get('nivel_codigo') or '').strip()
    if not titulo or not empresa or not nivel:
        return jsonify({'erro': 'Preencha título, empresa e nível'}), 400
    v = Vaga(titulo=titulo, descricao=d.get('descricao'), empresa=empresa, nivel_codigo=nivel,
             status='aberta', salario_min=d.get('salario_min') or None,
             salario_max=d.get('salario_max') or None, regime=d.get('regime'),
             localizacao=d.get('localizacao'))
    db.session.add(v)
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

@app.route('/api/vagas/<int:vid>/candidatar', methods=['POST'])
def candidatar(vid):
    v = Vaga.query.get(vid)
    if not v:
        return jsonify({'erro': 'Vaga não encontrada'}), 404
    d = request.get_json(force=True)
    nome = (d.get('nome') or '').strip()
    email = (d.get('email') or '').strip()
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
    ja = Candidatura.query.filter_by(vaga_id=vid, candidato_id=cand.id).first()
    if ja:
        return jsonify({'ok': True, 'msg': 'Você já está candidato a esta vaga',
                        'vaga': v.titulo, 'candidato': cand.nome, 'match_score': int(ja.match_score),
                        'status': ja.status})
    score = random.randint(62, 97)
    c = Candidatura(vaga_id=vid, candidato_id=cand.id, match_score=score, status='pendente')
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'msg': 'Candidatura enviada', 'vaga': v.titulo, 'empresa': v.empresa,
                    'candidato': cand.nome, 'email': email, 'match_score': score, 'status': 'pendente'})

# ================= INICIO =================
with app.app_context():
    db.create_all()
    criar_dados_iniciais()

if __name__ == '__main__':
    print()
    print('=' * 56)
    print('  🌐 ECOSSISTEMA DE RH INOVADOR v3.0')
    print('  🚀 Turbo: login, paineis e candidaturas reais')
    print('=' * 56)
    print('  🔗 Menu:   http://localhost:5000')
    print('  🔑 Login:  http://localhost:5000/login')
    print('  📊 PCS:    http://localhost:5000/pcs')
    print('=' * 56)
    print('  Pressione CTRL+C para parar')
    print()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
