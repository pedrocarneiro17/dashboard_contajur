from flask import Flask, request, render_template, redirect, url_for, flash
import pandas as pd
from datetime import datetime
import os
import re
from werkzeug.utils import secure_filename
import database as db  # Importa nosso novo módulo de banco de dados
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-forte' # Troque por uma chave segura
app.config['UPLOAD_FOLDER'] = 'Uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- INICIALIZAÇÃO DO BANCO DE DADOS ---
# Esta função garante que o banco de dados seja criado assim que o app iniciar.
with app.app_context():
    db.init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def process_excel(file_path):
    try:
        # Lê o cabeçalho para extrair o mês
        df_header = pd.read_excel(file_path, sheet_name='Página 1', nrows=1, header=None)
        first_row = df_header.iloc[0, 0]
        date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*à\s*(\d{2}/\d{2}/\d{4})', str(first_row))
        month = datetime.strptime(date_match.group(1), '%d/%m/%Y').strftime('%Y-%m') if date_match else datetime.now().strftime('%Y-%m')
        
        # Lê o Excel SEM pular linhas para acessar as linhas corretas
        df = pd.read_excel(file_path, sheet_name='Página 1', header=None)
        
        # Função auxiliar para converter valores BR para float
        def convert_br_to_float(value):
            """Converte valores no formato brasileiro (1.234,56) para float"""
            if pd.isna(value):
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            value_str = str(value).strip()
            value_str = value_str.replace('.', '').replace(',', '.')
            try:
                return float(value_str)
            except:
                return 0.0
        
        # Coluna L = índice 11 (A=0, B=1, C=2... L=11)
        # Linha 97 = índice 96 (primeira linha é índice 0) -> RECEITAS
        # Linha 98 = índice 97 -> DESPESAS
        total_revenue = convert_br_to_float(df.iloc[96, 11])  # Linha 97, Coluna L
        total_expenses_raw = convert_br_to_float(df.iloc[97, 11])  # Linha 98, Coluna L
        
        # Agora lê novamente COM cabeçalho para processar despesas detalhadas
        df_with_header = pd.read_excel(file_path, sheet_name='Página 1', skiprows=1)
        df_with_header['Descrição'] = df_with_header['Descrição'].astype(str)
        
        # Encontra a coluna 'Total' para processar despesas detalhadas
        if 'Total' in df_with_header.columns:
            total_col = 'Total'
        else:
            numeric_cols = df_with_header.select_dtypes(include=['number']).columns
            total_col = numeric_cols[-1] if len(numeric_cols) > 0 else df_with_header.columns[-1]
        
    except Exception as e:
        raise ValueError(f"Erro ao ler os totais de Receita/Despesa do Excel. Detalhe: {e}")

    # Cálculo de Honorários
    desc_normalized = df_with_header['Descrição'].str.strip().str.lower().str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    mask_honorarios = desc_normalized.str.startswith('honorario', na=False)
    honorarios_values = df_with_header.loc[mask_honorarios, total_col].apply(convert_br_to_float)
    total_fees = float(honorarios_values.sum())

    # Cálculos de lucro (SEM retiradas)
    total_expenses = total_expenses_raw
    profit_before_withdrawals = total_revenue - total_expenses
    net_profit = profit_before_withdrawals
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0

    # Distribuição inicial
    initial_profit_share = profit_before_withdrawals / 4.0
    shares = {
        'Lucas': initial_profit_share,
        'Thiago': initial_profit_share,
        'Ronaldo': initial_profit_share,
        'Reserva': initial_profit_share
    }

    totals_data = {
        "month": month,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "total_fees": total_fees,
        "net_profit": net_profit,
        "profit_margin": profit_margin,
        "share_lucas": shares['Lucas'],
        "share_thiago": shares['Thiago'],
        "share_ronaldo": shares['Ronaldo'],
        "share_reserva": shares['Reserva']
    }
    # Categorização de despesas com GRUPOS
    expenses_data = []
    categories = {
        'Despesas com Colaboradores': [
            'Salários',
            '13° Salário',
            'Férias',
            'Vale transporte',
            'Vale alimentação',
            'Plano de Saude',
            'Plano Odontologico',
            'Aniversário colaboradores',
            'Seguro de vida',
            'Feira, Mercado e outros',
            'SST',
            'Cursos e Palestras'
        ],
        'Impostos e Encargos': [
            'DAS - CONTAJUR',
            'FGTS - CONTAJUR',
            'DARF Previdenciário - Contajur'
        ],
        'Despesas de Escritório': [
            'Luz',
            'Telefonia',
            'Internet',
            'Aluguel',
            'Materiais de limpeza',
            'Uniformes',
            'Material de escritório',
            'Material de uso e consumo',
            'Segurança'
        ],
        'Mensalidades e Serviços': [
            'Mensalidade de Sistema',
            'Mensalidade T.I.',
            'Mensalidade Marketing Digital',
            'Mensalidade Revista Tecnica',
            'Mensalidade Aluguel de Impressora',
            'Mensalidade Associal Comercial',
            'Mensalidade Manutenção Web',
            'Implantação Sistema',
            'Mensalidade Personal',
            'Mensalidade Rede Cidada'
        ],
        'Manutenção e Investimentos': [
            'Manutenção Contajur (pintura, reforma, etc.)',
            'Aquisição imóvel/construção',
            'Combustivel e Manutençao Motos'
        ],
        'Reembolsos a Clientes': [
            'DAS - Reembolso Imposto Federal - Cliente',
            'Reembolso Imposto Estadual - Cliente',
            'Reembolso Imposto Estadual ICMS - Cliente',
            'GPS Autonomo - Reembolso Trabalhista- Cliente',
            'Abertura,baixa e alteração JUCEMG - Cliente',
            'Reembolso Certificado Digital',
            'FGTS - Reembolso trabalhista - Cliente',
            'Esocial - Reembolso trabalhista - Cliente',
            'Contrib Sindical - Reembolso trabalhista - cliente',
            'DARF - Retenção NF - Cliente',
            'ISSQN - Cliente',
            'DARF Previdenciário - Cliente',
            'Carnê Leão - cliente',
            'DAS Parcelamento - Reembolso de cliente'
        ],
        'Outras Despesas': [
            'Outras despesas',
            'Confraternização e Brindes fim de ano',
            'Multa e Juros',
            'Tarifa Bancaria'
        ]
    }
        
    for category, subcategories in categories.items():
        rows = df_with_header[df_with_header['Descrição'].str.strip().isin(subcategories)]
        for _, row in rows.iterrows():
            amount = convert_br_to_float(row[total_col])
            if amount != 0:
                expenses_data.append((month, category, row['Descrição'], float(amount)))

    # Sem retiradas do Excel
    withdrawals_data = []

    db.save_processed_excel_data(month, totals_data, expenses_data, withdrawals_data)
    
    return month

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    error = None
    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            error = 'Nenhum arquivo selecionado'
        elif file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            try:
                processed_month = process_excel(file_path)
                flash(f'Relatório do mês {processed_month} processado com sucesso!', 'success')
                return redirect(url_for('dashboard', month=processed_month))
            except ValueError as e:
                error = str(e)
        else:
            error = 'Extensão de arquivo não permitida. Use .xlsx'

    all_months = db.get_available_months()
    selected_month = request.args.get('month', all_months[0] if all_months else None)
    
    dashboard_data = db.get_dashboard_data(selected_month)
    
    return render_template('dashboard.html', 
                           months=all_months, 
                           selected_month=selected_month, 
                           error=error,
                           **dashboard_data)

@app.route('/add_withdrawal', methods=['POST'])
def add_withdrawal():
    month = request.form.get('month')
    person = request.form.get('person')
    amount_str = request.form.get('amount')
    try:
        amount = float(amount_str)
        db.add_manual_withdrawal(month, person, amount)
        flash(f'Retirada de {person} adicionada com sucesso!', 'success')
    except (ValueError, TypeError):
        flash('Erro: O valor da retirada deve ser um número.', 'error')
    
    return redirect(url_for('dashboard', month=month))

@app.route('/delete_withdrawal/<int:withdrawal_id>', methods=['POST'])
def delete_withdrawal(withdrawal_id):
    success, message = db.delete_manual_withdrawal(withdrawal_id)
    if success:
        flash('Retirada excluída com sucesso!', 'success')
    else:
        flash(f'Erro: {message}', 'error')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete/<string:month>', methods=['POST'])
def delete_month(month):
    try:
        db.delete_all_month_data(month)
        flash(f"Dados do mês {month} excluídos com sucesso.", 'success')
    except Exception as e:
        flash(f"Erro ao excluir o mês {month}: {e}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/compare')
def compare():
    selected_months = request.args.getlist('month')
    if not selected_months or len(selected_months) < 2:
        flash("Por favor, selecione pelo menos dois meses para comparar.", "error")
        return redirect(url_for('dashboard'))
    
    selected_months.sort()
    
    totals_comparison, category_comparison = db.get_compare_data(selected_months)
    
    return render_template('compare.html', 
                           selected_months=selected_months,
                           totals_comparison=totals_comparison,
                           category_comparison=category_comparison)
