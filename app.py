# -*- coding: utf-8 -*-
"""Ecossistema de RH Inovador v5.0 — visual inovador, detalhe de vaga, ranking e cadastro de candidato pelo admin."""

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
