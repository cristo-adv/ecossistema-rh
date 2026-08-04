# -*- coding: utf-8 -*-
"""Patch: telas de cadastro de empresa e vagas"""
import os, sqlite3

path = r'C:\ecossistema-rh\app.py'
db_path = r'C:\ecossistema-rh\ecossistema_rh.db'

with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

if 'cadastrar-empresa' in code:
    print('⚠️ Patch já aplicado anteriormente.')
else:
    # 1) Modelo Empresa
    modelos = '''
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
'''
    code = code.replace('class Candidatura(db.Model):', modelos + '\nclass Candidatura(db.Model):')
    print('✅ Modelo Empresa adicionado')

    # 2) Colunas extras na Vaga (modelo)
    old_vaga = """    status = db.Column(db.String(20), default='aberta')"""
    new_vaga = """    status = db.Column(db.String(20), default='aberta')
    salario_min = db.Column(db.Float)
    salario_max = db.Column(db.Float)
    regime = db.Column(db.String(30))
    localizacao = db.Column(db.String(120))"""
    if old_vaga in code:
        code = code.replace(old_vaga, new_vaga)
        print('✅ Colunas de vaga adicionadas ao modelo')
    else:
        print('⚠️ Modelo Vaga não encontrado para estender')

    # 3) ALTER TABLE no banco existente
    try:
        conn = sqlite3.connect(db_path)
        cols = [r[1] for r in conn.execute('PRAGMA table_info(vaga)').fetchall()]
        for nome, tipo in [('salario_min','FLOAT'), ('salario_max','FLOAT'), ('regime','VARCHAR(30)'), ('localizacao','VARCHAR(120)')]:
            if nome not in cols:
                conn.execute('ALTER TABLE vaga ADD COLUMN %s %s' % (nome, tipo))
        conn.commit(); conn.close()
        print('✅ Colunas adicionadas ao banco SQLite')
    except Exception as e:
        print('⚠️ Banco não atualizado (primeira execução?):', e)

    # 4) Rotas de cadastro (páginas + API)
    rotas = '''
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
'''
    code = code.replace('# ============ API JSON ============', rotas + '\n# ============ API JSON ============')
    print('✅ Rotas de cadastro adicionadas')

    # 5) Acesso rápido no menu
    old_acesso = """html += '<div class="painel"><h4>Acesso Rápido</h4><div class="status"><div class="item"><a class="link" href="/login">🔑 Entrar com credenciais</a></div><div class="item"><a class="link" href="/registro">📝 Criar conta</a></div><div class="item"><a class="link" href="/api/health">📡 Health Check (JSON)</a></div></div></div>'"""
    new_acesso = """html += '<div class="painel"><h4>Acesso Rápido</h4><div class="status"><div class="item"><a class="link" href="/login">🔑 Entrar</a></div><div class="item"><a class="link" href="/registro">📝 Criar conta</a></div><div class="item"><a class="link" href="/cadastrar-empresa">🏢 Cadastrar Empresa</a></div><div class="item"><a class="link" href="/cadastrar-vaga">💼 Publicar Vaga</a></div><div class="item"><a class="link" href="/api/health">📡 Health Check</a></div></div></div>'"""
    if old_acesso in code:
        code = code.replace(old_acesso, new_acesso)
        print('✅ Acesso rápido atualizado no menu')
    else:
        print('⚠️ Bloco Acesso Rápido não encontrado')

    # 6) Botão na página de vagas
    old_vagas_h = """html = '<h1>Vagas <span>// Oportunidades</span></h1><p class="sub">' + str(len(lista)) + ' vagas abertas no ecossistema</p><div class="grade">'"""
    new_vagas_h = """html = '<p style="text-align:right;margin-bottom:12px"><a class="link" href="/cadastrar-vaga">➕ Nova Vaga</a></p><h1>Vagas <span>// Oportunidades</span></h1><p class="sub">' + str(len(lista)) + ' vagas abertas no ecossistema</p><div class="grade">'"""
    if old_vagas_h in code:
        code = code.replace(old_vagas_h, new_vagas_h)
        print('✅ Botão Nova Vaga adicionado')

    # 7) Salário/regime nos cards de vaga
    old_card = """<p style="margin-top:8px">🏢 ' + v.empresa + ' • Nível <b>' + v.nivel_codigo + '</b></p>"""
    new_card = """<p style="margin-top:8px">🏢 ' + v.empresa + ' • Nível <b>' + v.nivel_codigo + '</b></p><p style="margin-top:6px;font-size:12px;color:#10b981">' + (('💰 ' + fmt(v.salario_min) + ' – ' + fmt(v.salario_max)) if v.salario_min and v.salario_max else '💰 A combinar') + ' • ' + (v.regime or 'remoto') + '</p>"""
    if old_card in code:
        code = code.replace(old_card, new_card)
        print('✅ Salário e regime exibidos nas vagas')

    # 8) Página de empresas com dados reais + botão
    old_emp = """html = '<h1>Empresas <span>// Contratantes</span></h1><p class="sub">' + str(len(lista)) + ' organizações no ecossistema</p><div class="painel"><table class="tabela"><thead><tr><th>Razão Social</th><th>E-mail</th><th>Status</th></tr></thead><tbody>'"""
    new_emp = """html = '<p style="text-align:right;margin-bottom:12px"><a class="link" href="/cadastrar-empresa">➕ Cadastrar Empresa</a></p><h1>Empresas <span>// Contratantes</span></h1><p class="sub">' + str(len(lista)) + ' organizações no ecossistema</p><div class="painel"><table class="tabela"><thead><tr><th>Razão Social</th><th>E-mail</th><th>Setor</th><th>Status</th></tr></thead><tbody>'"""
    if old_emp in code:
        code = code.replace(old_emp, new_emp)
        print('✅ Página de empresas atualizada')

    # 9) Tabela de empresas com setor
    old_td = """'<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td><span class="pill aberta">Verificada</span></td></tr>'"""
    new_td = """'<tr><td><b>' + u.nome + '</b></td><td>' + u.email + '</td><td>' + (Empresa.query.filter_by(usuario_id=u.id).first().setor if Empresa.query.filter_by(usuario_id=u.id).first() else '-') + '</td><td><span class="pill aberta">Verificada</span></td></tr>'"""
    if old_td in code:
        code = code.replace(old_td, new_td)
        print('✅ Tabela de empresas com setor')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(code)
    print('🎉 Patch aplicado com sucesso! Reinicie o servidor.')
