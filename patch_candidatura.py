# -*- coding: utf-8 -*-
"""Patch: adiciona tela de formulario de candidatura ao app.py"""
path = r'C:\ecossistema-rh\app.py'

with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

# ========== 1. SUBSTITUI O ENDPOINT ANTIGO PELA TELA DE FORMULÁRIO ==========
old_endpoint = """@app.route('/api/vagas/<int:vid>/candidatar')
def candidatar(vid):
    v = Vaga.query.get(vid)
    if not v:
        return jsonify({'erro':'Vaga não encontrada'}), 404
    cand = Usuario.query.filter_by(tipo='candidato').first()
    if not cand:
        return jsonify({'erro':'Nenhum candidato cadastrado'}), 400
    score = random.randint(62, 97)
    c = Candidatura(vaga_id=vid, candidato_id=cand.id, match_score=score, status='pendente')
    db.session.add(c); db.session.commit()
    return jsonify({'ok':True,'vaga':v.titulo,'candidato':cand.nome,'match_score':score,'status':'pendente'})"""

new_endpoint = """@app.route('/vagas/<int:vid>/candidatar')
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
    return jsonify({'ok':True,'vaga':v.titulo,'empresa':v.empresa,'candidato':cand.nome,'email':email,'match_score':score,'status':'pendente'})"""

if old_endpoint in code:
    code = code.replace(old_endpoint, new_endpoint)
    print("✅ Endpoint de candidatura atualizado com formulário")
else:
    print("⚠️ Endpoint antigo não encontrado — verificando se já está atualizado")

# ========== 2. ATUALIZA O LINK DO CARD DE VAGA ==========
old_link = 'href="/api/vagas/\' + str(v.id) + \'/candidatar"'
new_link = 'href="/vagas/\' + str(v.id) + \'/candidatar"'
if old_link in code:
    code = code.replace(old_link, new_link)
    print("✅ Link do card atualizado para abrir o formulário")
else:
    print("⚠️ Link antigo não encontrado (verifique)")

# ========== 3. GRAVA ==========
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print("🎉 app.py atualizado com sucesso!")
print("🔄 Reinicie o servidor para aplicar as mudanças")
