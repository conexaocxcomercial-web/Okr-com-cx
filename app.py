import os
from flask import Flask, render_template, request, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_super_secreta_2026")

# Conexão com o Supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- DECORATOR PARA PROTEGER ROTAS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROTAS DE AUTENTICAÇÃO ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Procura o utilizador e os dados do cliente vinculado
        res = supabase.table('users').select('*, clients(name)').eq('username', username).eq('password', password).execute()
        
        if res.data:
            user = res.data[0]
            session['user_id'] = user['id']
            session['client_id'] = user['client_id']
            session['user_name'] = user['name']
            session['client_name'] = user['clients']['name']
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Utilizador ou senha inválidos.")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ROTA PRINCIPAL ---
@app.route('/')
@login_required
def index():
    selected_dept_id = request.args.get('dept_id')
    client_id = session['client_id']
    
    # Busca dados APENAS do cliente logado
    res_macro = supabase.table('macro_objectives').select('*').eq('client_id', client_id).execute()
    res_dept = supabase.table('departments').select('*').eq('client_id', client_id).order('name').execute()
    
    dept_details = None
    if selected_dept_id:
        # Carrega a árvore: Objetivo -> KRs -> Tarefas
        res_details = supabase.table('dept_objectives')\
            .select('*, key_results(*, tasks(*))')\
            .eq('department_id', selected_dept_id)\
            .execute()
        dept_details = res_details.data

    return render_template('index.html', 
                           macro_objectives=res_macro.data, 
                           departments=res_dept.data,
                           selected_dept_id=selected_dept_id,
                           dept_details=dept_details,
                           session=session)

# --- GESTÃO ESTRATÉGICA ---
@app.route('/macro/save', methods=['POST'])
@login_required
def save_macro():
    title = request.form.get('title')
    cycle = request.form.get('cycle')
    macro_id = request.form.get('macro_id')
    client_id = session['client_id']
    
    if macro_id: 
        supabase.table('macro_objectives').update({'title': title, 'cycle': cycle}).eq('id', macro_id).eq('client_id', client_id).execute()
    else: 
        existing = supabase.table('macro_objectives').select('id').eq('client_id', client_id).execute()
        if not existing.data:
            supabase.table('macro_objectives').insert({'title': title, 'cycle': cycle, 'client_id': client_id}).execute()
    return redirect(url_for('index'))

@app.route('/department/save', methods=['POST'])
@login_required
def save_department():
    name = request.form.get('name')
    dept_id = request.form.get('dept_id')
    client_id = session['client_id']
    
    if dept_id: 
        supabase.table('departments').update({'name': name}).eq('id', dept_id).eq('client_id', client_id).execute()
    else: 
        supabase.table('departments').insert({'name': name, 'client_id': client_id}).execute()
    return redirect(url_for('index'))

# --- CRIAÇÃO OPERACIONAL ---
@app.route('/operational/create', methods=['POST'])
@login_required
def create_operational():
    item_type = request.form.get('type')
    dept_id = request.form.get('dept_id')
    parent_id = request.form.get('parent_id')
    client_id = session['client_id']
    
    if item_type == 'dept_objective':
        macro_res = supabase.table('macro_objectives').select('id').eq('client_id', client_id).limit(1).execute()
        macro_id = macro_res.data[0]['id'] if macro_res.data else None
        if macro_id:
            supabase.table('dept_objectives').insert({
                'title': request.form.get('title'),
                'department_id': dept_id,
                'macro_objective_id': macro_id
            }).execute()
            
    elif item_type == 'kr':
        supabase.table('key_results').insert({
            'description': request.form.get('description'),
            'dept_objective_id': parent_id,
            'target_value': float(request.form.get('target_value')),
            'current_value': 0.0
        }).execute()
        
    elif item_type == 'task':
        deadline = request.form.get('deadline')
        supabase.table('tasks').insert({
            'description': request.form.get('description'),
            'kr_id': parent_id,
            'owner_name': request.form.get('owner_name'),
            'deadline': deadline if deadline else None,
            'deliverable_link': request.form.get('deliverable_link'),
            'status': 'Não iniciado'
        }).execute()

    return redirect(url_for('index', dept_id=dept_id))

# --- EDIÇÃO OPERACIONAL (Com correções de Bugs) ---
@app.route('/operational/update', methods=['POST'])
@login_required
def update_operational():
    item_type = request.form.get('type')
    item_id = request.form.get('item_id')
    dept_id = request.form.get('dept_id')

    if item_type == 'dept_objective':
        # Editar Título do Objetivo
        supabase.table('dept_objectives').update({
            'title': request.form.get('title')
        }).eq('id', item_id).execute()

    elif item_type == 'kr':
        # Edição completa do KR: Título, Atual e Meta
        current_val = request.form.get('current_value')
        target_val = request.form.get('target_value')
        supabase.table('key_results').update({
            'description': request.form.get('description'),
            'current_value': float(current_val) if current_val else 0.0,
            'target_value': float(target_val) if target_val else 0.0
        }).eq('id', item_id).execute()

    elif item_type == 'task':
        # Edição completa da Tarefa com trava para Data nula
        deadline = request.form.get('deadline')
        supabase.table('tasks').update({
            'description': request.form.get('description'),
            'owner_name': request.form.get('owner_name'),
            'deadline': deadline if deadline else None,
            'deliverable_link': request.form.get('deliverable_link'),
            'status': request.form.get('status')
        }).eq('id', item_id).execute()

    return redirect(url_for('index', dept_id=dept_id))
    
# --- EXCLUSÃO OPERACIONAL ---
@app.route('/operational/delete', methods=['POST'])
@login_required
def delete_operational():
    item_type = request.form.get('type')
    item_id = request.form.get('item_id')
    dept_id = request.form.get('dept_id')

    if item_type == 'dept_objective':
        supabase.table('dept_objectives').delete().eq('id', item_id).execute()
    elif item_type == 'kr':
        supabase.table('key_results').delete().eq('id', item_id).execute()
    elif item_type == 'task':
        supabase.table('tasks').delete().eq('id', item_id).execute()

    return redirect(url_for('index', dept_id=dept_id))

if __name__ == '__main__':
    # Em produção (Render), o Gunicorn ignora isto, mas ajuda no teste local
    app.run(debug=True)
