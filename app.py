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

# --- ROTA PRINCIPAL (ESTRATÉGIA) ---
@app.route('/')
@login_required
def index():
    selected_dept_id = request.args.get('dept_id')
    client_id = session['client_id']
    
    res_macro = supabase.table('macro_objectives').select('*').eq('client_id', client_id).execute()
    res_dept = supabase.table('departments').select('*').eq('client_id', client_id).order('name').execute()
    
    dept_details = None
    if selected_dept_id:
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

# --- ROTA DO DASHBOARD (NOVA) ---
@app.route('/dashboard')
@login_required
def dashboard():
    client_id = session['client_id']
    
    # Filtros recebidos na URL
    f_dept = request.args.get('dept_id')
    f_cycle = request.args.get('cycle')
    f_owner = request.args.get('owner')
    
    # Buscar os Departamentos do Cliente
    res_dept = supabase.table('departments').select('*').eq('client_id', client_id).order('name').execute()
    departments = res_dept.data
    dept_ids = [d['id'] for d in departments]
    
    all_objs = []
    if dept_ids:
        res_objs = supabase.table('dept_objectives').select('*, key_results(*, tasks(*))').in_('department_id', dept_ids).execute()
        all_objs = res_objs.data

    owners = set()
    task_status_counts = {'Finalizado': 0, 'Em andamento': 0, 'Pausado': 0, 'Não iniciado': 0}
    dept_progress = {d['id']: {'name': d['name'], 'kr_pct_sum': 0, 'kr_count': 0} for d in departments}
    
    total_kr_pct_sum = 0
    total_kr_count = 0
    kr_ranking = []

    for obj in all_objs:
        # LÓGICA DOS CICLOS (T1, T2, T3, T4 baseados no mês de criação)
        created_at = obj.get('created_at', '')
        obj_cycle = "T1"
        if created_at and len(created_at) >= 7:
            month = int(created_at[5:7])
            if month <= 3: obj_cycle = "T1"
            elif month <= 6: obj_cycle = "T2"
            elif month <= 9: obj_cycle = "T3"
            else: obj_cycle = "T4"
            
        # Aplicar Filtro de Ciclo e Departamento
        if f_cycle and obj_cycle != f_cycle: continue
        if f_dept and obj['department_id'] != f_dept: continue
        
        for kr in obj.get('key_results', []):
            tv = kr['target_value']
            cv = kr['current_value']
            pct = (cv / tv * 100) if tv and tv > 0 else 0
            pct = min(pct, 100) # Limita a 100%
            
            total_kr_pct_sum += pct
            total_kr_count += 1
            
            did = obj['department_id']
            if did in dept_progress:
                dept_progress[did]['kr_pct_sum'] += pct
                dept_progress[did]['kr_count'] += 1
            
            kr_ranking.append({'name': kr['description'], 'pct': round(pct)})
            
            for task in kr.get('tasks', []):
                owner = task.get('owner_name')
                if owner:
                    owner_clean = owner.strip()
                    if owner_clean: owners.add(owner_clean)
                else:
                    owner_clean = ""
                
                # Aplicar Filtro de Responsável (Apenas para a contagem de tarefas)
                if f_owner and owner_clean != f_owner: continue
                
                st = task.get('status', 'Não iniciado')
                if st in task_status_counts:
                    task_status_counts[st] += 1
                else:
                    task_status_counts['Não iniciado'] += 1

    # Preparar Dados Finais para os Gráficos
    geral_pct = round(total_kr_pct_sum / total_kr_count) if total_kr_count > 0 else 0
    
    dept_chart_labels = []
    dept_chart_data = []
    for did, data in dept_progress.items():
        if data['kr_count'] > 0:
            dept_chart_labels.append(data['name'])
            dept_chart_data.append(round(data['kr_pct_sum'] / data['kr_count']))
            
    kr_ranking = sorted(kr_ranking, key=lambda x: x['pct'], reverse=True)[:5]
    sorted_owners = sorted(list(owners))

    return render_template('dashboard.html',
                           departments=departments,
                           owners=sorted_owners,
                           f_dept=f_dept,
                           f_cycle=f_cycle,
                           f_owner=f_owner,
                           geral_pct=geral_pct,
                           dept_chart_labels=dept_chart_labels,
                           dept_chart_data=dept_chart_data,
                           task_status_counts=task_status_counts,
                           kr_ranking=kr_ranking,
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

# --- EDIÇÃO OPERACIONAL ---
@app.route('/operational/update', methods=['POST'])
@login_required
def update_operational():
    item_type = request.form.get('type')
    item_id = request.form.get('item_id')
    dept_id = request.form.get('dept_id')

    if item_type == 'dept_objective':
        supabase.table('dept_objectives').update({
            'title': request.form.get('title')
        }).eq('id', item_id).execute()

    elif item_type == 'kr':
        current_val = request.form.get('current_value')
        target_val = request.form.get('target_value')
        supabase.table('key_results').update({
            'description': request.form.get('description'),
            'current_value': float(current_val) if current_val else 0.0,
            'target_value': float(target_val) if target_val else 0.0
        }).eq('id', item_id).execute()

    elif item_type == 'task':
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
    app.run(debug=True)
