# ================= ADMIN: CADASTRAR CANDIDATO =================
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = usuario_atual()
        if not u or u.tipo != 'admin':
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper

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
