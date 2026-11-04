from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, make_response
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import pandas as pd
import os
import io

app = Flask(__name__)
app.secret_key = 'cle_secrete_cave_2026_professionnel'

def get_db():
    conn = sqlite3.connect('cave.db')
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def fmt(montant):
    try:
        if montant is None: return "0"
        return f"{float(montant):,.0f}".replace(',', ' ')
    except:
        return "0"

@app.context_processor
def injecter_fmt():
    return dict(fmt=fmt)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("⚠️ Vous devez vous connecter.", "warning")
            return redirect(url_for('connexion'))
        return f(*args, **kwargs)
    return decorated_function

def check_access(acces_key):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash("⚠️ Vous devez vous connecter.", "warning")
                return redirect(url_for('connexion'))
            if not session.get(acces_key):
                flash(f"⛔ Accès non autorisé.", "danger")
                session.clear()
                return redirect(url_for('connexion'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ==========================================
# 0. CONNEXION / DÉCONNEXION
# ==========================================
@app.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if request.method == 'POST':
        nom = request.form['nom_utilisateur'].strip()
        mdp = request.form['mot_de_passe']
        mdp_hash = hash_password(mdp)
        conn = get_db()
        user = conn.execute('SELECT * FROM utilisateurs WHERE nom = ? AND mot_de_passe = ? AND actif = 1', (nom, mdp_hash)).fetchone()
        if user:
            acces_dashboard = int(user['acces_dashboard'] or 0)
            acces_saisie = int(user['acces_saisie'] or 0)
            acces_cloture = int(user['acces_cloture'] or 0)
            acces_appro = int(user['acces_appro'] or 0)
            acces_historique = int(user['acces_historique'] or 0)
            acces_clients = int(user['acces_clients'] or 0)
            acces_paiements = int(user['acces_paiements'] or 0)
            acces_inventaire = int(user['acces_inventaire'] or 0)
            acces_comptes = int(user['acces_comptes'] or 0)
            has_access = any([acces_dashboard, acces_saisie, acces_cloture, acces_appro, acces_historique, acces_clients, acces_paiements, acces_inventaire, acces_comptes])
            if not has_access:
                conn.close()
                flash("⛔ Votre compte n'a aucune autorisation.", "danger")
                return render_template('connexion.html')
            if not acces_dashboard: acces_dashboard = 1
            session['user_id'] = user['id']
            session['user_nom'] = user['nom']
            session['user_role'] = user['role']
            session['acces_dashboard'] = bool(acces_dashboard)
            session['acces_saisie'] = bool(acces_saisie)
            session['acces_cloture'] = bool(acces_cloture)
            session['acces_appro'] = bool(acces_appro)
            session['acces_historique'] = bool(acces_historique)
            session['acces_clients'] = bool(acces_clients)
            session['acces_paiements'] = bool(acces_paiements)
            session['acces_inventaire'] = bool(acces_inventaire)
            session['acces_comptes'] = bool(acces_comptes)
            conn.close()
            flash(f"✅ Bienvenue {user['nom']} !", "success")
            return redirect(url_for('dashboard'))
        else:
            conn.close()
            flash("❌ Identifiants incorrects.", "danger")
    return render_template('connexion.html')

@app.route('/deconnexion')
def deconnexion():
    session.clear()
    return redirect(url_for('connexion'))

# ==========================================
# 0.bis COMPTES
# ==========================================
@app.route('/comptes', methods=['GET', 'POST'])
@check_access('acces_comptes')
def comptes():
    conn = get_db()
    if request.method == 'POST':
        nom = request.form['nom'].strip()
        role = request.form['role']
        mdp = request.form['mot_de_passe']
        mdp2 = request.form.get('confirmation_mdp', '')
        jours = ','.join(request.form.getlist('jours'))
        acces = {k: 1 if request.form.get(k) else 0 for k in ['acces_dashboard', 'acces_saisie', 'acces_cloture', 'acces_appro', 'acces_historique', 'acces_clients', 'acces_paiements', 'acces_inventaire', 'acces_comptes']}
        if mdp != mdp2: flash("⚠️ Mots de passe différents.", "danger"); conn.close(); return redirect(url_for('comptes'))
        if conn.execute('SELECT id FROM utilisateurs WHERE nom = ?', (nom,)).fetchone(): flash("⚠️ Utilisateur existe déjà.", "warning"); conn.close(); return redirect(url_for('comptes'))
        conn.execute('''INSERT INTO utilisateurs (nom, role, mot_de_passe, jours_travail, actif, acces_dashboard, acces_saisie, acces_cloture, acces_appro, acces_historique, acces_clients, acces_paiements, acces_inventaire, acces_comptes) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (nom, role, hash_password(mdp), jours, acces['acces_dashboard'], acces['acces_saisie'], acces['acces_cloture'], acces['acces_appro'], acces['acces_historique'], acces['acces_clients'], acces['acces_paiements'], acces['acces_inventaire'], acces['acces_comptes']))
        conn.commit(); conn.close()
        flash("✅ Compte créé !", "success"); return redirect(url_for('comptes'))
    users = conn.execute('SELECT * FROM utilisateurs ORDER BY nom').fetchall(); conn.close()
    return render_template('comptes.html', utilisateurs=users)

@app.route('/desactiver_compte/<int:uid>')
@check_access('acces_comptes')
def desactiver_compte(uid):
    conn = get_db(); conn.execute('UPDATE utilisateurs SET actif = 0 WHERE id = ?', (uid,)); conn.commit(); conn.close(); return redirect(url_for('comptes'))

@app.route('/reactiver_compte/<int:uid>')
@check_access('acces_comptes')
def reactiver_compte(uid):
    conn = get_db(); conn.execute('UPDATE utilisateurs SET actif = 1 WHERE id = ?', (uid,)); conn.commit(); conn.close(); return redirect(url_for('comptes'))

@app.route('/supprimer_compte/<int:uid>')
@check_access('acces_comptes')
def supprimer_compte(uid):
    conn = get_db()
    if uid == session.get('user_id'): flash("⚠️ Vous ne pouvez pas supprimer votre propre compte.", "warning")
    else: conn.execute('DELETE FROM utilisateurs WHERE id = ?', (uid,)); conn.commit(); flash("✅ Compte supprimé.", "success")
    conn.close(); return redirect(url_for('comptes'))

@app.route('/modifier_autorisations/<int:uid>', methods=['GET', 'POST'])
@check_access('acces_comptes')
def modifier_autorisations(uid):
    conn = get_db()
    user = conn.execute('SELECT * FROM utilisateurs WHERE id = ?', (uid,)).fetchone()
    if request.method == 'POST':
        acces = {k: 1 if request.form.get(k) else 0 for k in ['acces_dashboard', 'acces_saisie', 'acces_cloture', 'acces_appro', 'acces_historique', 'acces_clients', 'acces_paiements', 'acces_inventaire', 'acces_comptes']}
        conn.execute('''UPDATE utilisateurs SET acces_dashboard=?, acces_saisie=?, acces_cloture=?, acces_appro=?, acces_historique=?, acces_clients=?, acces_paiements=?, acces_inventaire=?, acces_comptes=? WHERE id=?''', (acces['acces_dashboard'], acces['acces_saisie'], acces['acces_cloture'], acces['acces_appro'], acces['acces_historique'], acces['acces_clients'], acces['acces_paiements'], acces['acces_inventaire'], acces['acces_comptes'], uid))
        conn.commit(); conn.close(); flash("✅ Autorisations mises à jour !", "success"); return redirect(url_for('comptes'))
    conn.close(); return render_template('modifier_autorisations.html', user=user)

# ==========================================
# 1. DASHBOARD
# ==========================================
@app.route('/')
@check_access('acces_dashboard')
def dashboard():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d'); mois = today[:7]
    stats = {
        'total_produits': conn.execute('SELECT COUNT(*) as c FROM produits').fetchone()['c'],
        'stock_hall': conn.execute('SELECT COALESCE(SUM(quantite), 0) as s FROM stocks WHERE emplacement="Hall"').fetchone()['s'],
        'valeur_stock': fmt(conn.execute('SELECT COALESCE(SUM(s.quantite * p.prix_vente_hall), 0) as v FROM stocks s JOIN produits p ON s.produit_id = p.id WHERE s.emplacement="Hall"').fetchone()['v']),
        'total_credits': fmt(conn.execute('SELECT COALESCE(SUM(solde_du), 0) as c FROM clients').fetchone()['c']),
        'total_clients': conn.execute('SELECT COUNT(*) as c FROM clients').fetchone()['c'],
        'ventes_jour': conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = ?', (today,)).fetchone()['v'],
        'ventes_mois': fmt(conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE strftime("%Y-%m", date_heure) = ?', (mois,)).fetchone()['v']),
    }
    mauvais_payeurs = conn.execute('SELECT nom, solde_du, plafond_credit FROM clients WHERE solde_du > 0 ORDER BY solde_du DESC LIMIT 5').fetchall()
    labels_jours, data_ventes = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        labels_jours.append((datetime.now() - timedelta(days=i)).strftime('%d/%m'))
        data_ventes.append(conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = ?', (d,)).fetchone()['v'])
    stats_paiement = conn.execute('SELECT mode_paiement, SUM(total) as total_montant FROM ventes WHERE strftime("%Y-%m", date_heure) = ? GROUP BY mode_paiement', (mois,)).fetchall()
    total_gen = sum(s['total_montant'] for s in stats_paiement)
    labels_p, data_p, data_pct, couleurs_p = [], [], [], []
    cmap = {'especes': '#28a745', 'wave': '#0d6efd', 'orange_money': '#fd7e14', 'credit': '#dc3545'}
    for s in stats_paiement:
        pct = round((s['total_montant'] / total_gen * 100), 1) if total_gen > 0 else 0
        labels_p.append(f"{s['mode_paiement'].replace('_', ' ').title()} ({pct}%)"); data_p.append(s['total_montant']); data_pct.append(pct); couleurs_p.append(cmap.get(s['mode_paiement'], '#6c757d'))
    top_cats = conn.execute('SELECT p.categorie, SUM(lv.montant_kit) as total_ca FROM lignes_vente lv JOIN produits p ON lv.produit_id = p.id JOIN ventes v ON lv.vente_id = v.id WHERE strftime("%Y-%m", v.date_heure) = ? GROUP BY p.categorie ORDER BY total_ca DESC LIMIT 3', (mois,)).fetchall()
    labels_c, data_c, couleurs_c = [], [], ['#1890ff', '#52c41a', '#fa8c16']
    details_cats = {}
    for c in top_cats:
        labels_c.append(c['categorie']); data_c.append(c['total_ca'])
        prods = conn.execute('SELECT p.nom, SUM(lv.quantite) as total_qte, SUM(lv.montant_kit) as total_ca FROM lignes_vente lv JOIN produits p ON lv.produit_id = p.id JOIN ventes v ON lv.vente_id = v.id WHERE p.categorie = ? AND strftime("%Y-%m", v.date_heure) = ? GROUP BY p.id ORDER BY total_ca DESC LIMIT 5', (c['categorie'], mois)).fetchall()
        details_cats[c['categorie']] = [{'nom': p['nom'], 'qte': p['total_qte'], 'ca': p['total_ca'], 'pct': round((p['total_ca']/c['total_ca']*100), 1) if c['total_ca']>0 else 0} for p in prods]
    alertes_stock = conn.execute('SELECT p.nom, s.quantite, p.seuil_alerte FROM stocks s JOIN produits p ON s.produit_id = p.id WHERE s.emplacement = "Hall" AND s.quantite <= p.seuil_alerte ORDER BY s.quantite ASC LIMIT 5').fetchall()
    dernieres_ventes = conn.execute('SELECT v.date_heure, v.total, v.mode_paiement, c.nom as client_nom, COUNT(lv.id) as nb_produits FROM ventes v LEFT JOIN clients c ON v.client_id = c.id LEFT JOIN lignes_vente lv ON v.id = lv.vente_id GROUP BY v.id ORDER BY v.date_heure DESC LIMIT 10').fetchall()
    conn.close()
    return render_template('dashboard.html', date_jour=datetime.now().strftime('%d/%m/%Y'), mauvais_payeurs=mauvais_payeurs, labels_jours=labels_jours, data_ventes=data_ventes, labels_paiement=labels_p, data_paiement=data_p, data_pourcentage=data_pct, couleurs_paiement=couleurs_p, labels_cat=labels_c, data_cat=data_c, couleurs_cat=couleurs_c, details_categories=details_cats, alertes_stock=alertes_stock, dernieres_ventes=dernieres_ventes, **stats)

# ==========================================
# 2. PRODUITS
# ==========================================
@app.route('/produits')
@login_required
def produits():
    conn = get_db()
    liste = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = "Hall" ORDER BY p.categorie, p.nom').fetchall()
    conn.close()
    return render_template('produits.html', produits=liste)

@app.route('/telecharger_modele_produits')
@login_required
def telecharger_modele_produits():
    df = pd.DataFrame({'Nom': ['Ex: HEINEKEN 33'], 'Categorie': ['AUTRES'], 'Prix Achat': [500], 'Prix Vente Hall': [700], 'Prix Kit': [2000], 'Prix Bar': [800], 'Stock': [100]})
    path = os.path.join(os.getcwd(), 'modele_import_produits.xlsx')
    df.to_excel(path, index=False); return send_file(path, as_attachment=True)

@app.route('/importer_produits', methods=['POST'])
@login_required
def importer_produits():
    try:
        f = request.files['fichier_excel']
        if not f.filename.endswith(('.xlsx', '.xls')): flash("❌ Fichier invalide.", "danger"); return redirect(url_for('produits'))
        df = pd.read_excel(f); df.columns = [str(c).upper().strip() for c in df.columns]
        cn = next((c for c in df.columns if 'NOM' in c or 'PRODUIT' in c), None)
        if not cn: flash("❌ Colonne Nom introuvable.", "danger"); return redirect(url_for('produits'))
        df = df.dropna(subset=[cn]); conn = get_db(); count = 0
        for _, r in df.iterrows():
            nom = str(r[cn]).strip()
            if not nom or nom.upper() in ['TOTAL', 'NAN', 'EX: HEINEKEN 33']: continue
            cat = str(r.get(next((c for c in df.columns if 'CATEG' in c), ''), '')).strip() or "AUTRES"
            pa = float(r.get(next((c for c in df.columns if 'ACHAT' in c or 'COUT' in c), ''), 0) or 0)
            pv = float(r.get(next((c for c in df.columns if 'VENTE' in c or 'HALL' in c), ''), pa) or pa)
            pk = float(r.get(next((c for c in df.columns if 'KIT' in c), ''), 0) or 0)
            pb = float(r.get(next((c for c in df.columns if 'BAR' in c), ''), 0) or 0)
            st = int(r.get(next((c for c in df.columns if 'STOCK' in c or 'QTE' in c), ''), 0) or 0)
            conn.execute('INSERT OR IGNORE INTO produits (nom, categorie, prix_achat, prix_vente_hall, prix_kit, prix_bar, seuil_alerte) VALUES (?, ?, ?, ?, ?, ?, 5)', (nom, cat, pa, pv, pk, pb))
            pid = conn.execute('SELECT id FROM produits WHERE nom = ?', (nom,)).fetchone()[0]
            if st > 0: conn.execute('INSERT OR IGNORE INTO stocks (produit_id, emplacement, quantite) VALUES (?, "Hall", ?)', (pid, st))
            count += 1
        conn.commit(); conn.close(); flash(f"✅ {count} produits importés.", "success")
    except Exception as e: flash(f"❌ Erreur: {e}", "danger")
    return redirect(url_for('produits'))

@app.route('/modifier_produit/<int:pid>', methods=['GET', 'POST'])
@login_required
def modifier_produit(pid):
    conn = get_db()
    if request.method == 'POST':
        nom = request.form['nom'].strip()
        prix_hall = request.form['prix_hall']
        prix_kit = request.form.get('prix_kit', 0) or 0
        prix_bar = request.form.get('prix_bar', 0) or 0
        existe = conn.execute('SELECT id FROM produits WHERE nom = ? AND id != ?', (nom, pid)).fetchone()
        if existe:
            flash("⚠️ Ce nom de produit existe déjà.", "warning")
            conn.close()
            return redirect(url_for('modifier_produit', pid=pid))
        conn.execute('UPDATE produits SET nom=?, prix_vente_hall=?, prix_kit=?, prix_bar=? WHERE id=?', (nom, prix_hall, prix_kit, prix_bar, pid))
        conn.commit(); conn.close()
        flash("✅ Produit modifié !", "success")
        return redirect(url_for('produits'))
    p = conn.execute('SELECT * FROM produits WHERE id = ?', (pid,)).fetchone()
    conn.close()
    return render_template('modifier_produit.html', produit=p)

@app.route('/supprimer_produit/<int:pid>')
@login_required
def supprimer_produit(pid):
    conn = get_db()
    nb_ventes = conn.execute('SELECT COUNT(*) as c FROM lignes_vente WHERE produit_id = ?', (pid,)).fetchone()['c']
    if nb_ventes > 0:
        flash(f"⚠️ Impossible de supprimer : ce produit a été vendu {nb_ventes} fois.", "danger")
    else:
        conn.execute('DELETE FROM stocks WHERE produit_id = ?', (pid,))
        conn.execute('DELETE FROM produits WHERE id = ?', (pid,))
        conn.commit()
        flash("✅ Produit supprimé.", "success")
    conn.close()
    return redirect(url_for('produits'))

# ==========================================
# 3. VENTES DU JOUR (Caisse)
# ==========================================
@app.route('/caisse', methods=['GET', 'POST'])
@check_access('acces_saisie')
def caisse():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    cloture = conn.execute('SELECT id FROM clotures_caisse WHERE date_cloture = ?', (today,)).fetchone()
    caisse_fermee = cloture is not None
    
    if request.method == 'POST':
        if caisse_fermee:
            flash("⛔ La caisse est déjà clôturée.", "danger"); conn.close(); return redirect(url_for('caisse'))
        
        dh = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_vente = 0
        lignes = []
        
        for p in conn.execute('SELECT * FROM produits').fetchall():
            pid = p['id']
            qte_hall = int(request.form.get(f'qte_hall_{pid}', 0) or 0)
            qte_kit = int(request.form.get(f'qte_kit_{pid}', 0) or 0)
            qte_bar = int(request.form.get(f'qte_bar_{pid}', 0) or 0)
            
            if qte_hall + qte_kit + qte_bar > 0:
                mt_hall = qte_hall * p['prix_vente_hall']
                mt_kit = qte_kit * (p['prix_kit'] or p['prix_vente_hall'])
                mt_bar = qte_bar * (p['prix_bar'] or p['prix_vente_hall'])
                total_ligne = mt_hall + mt_kit + mt_bar
                
                if total_ligne > 0:
                    total_vente += total_ligne
                    if qte_hall > 0:
                        lignes.append({'pid': pid, 'qte': qte_hall, 'prix': p['prix_vente_hall'], 'mt': mt_hall, 'type': 'hall'})
                        conn.execute('UPDATE stocks SET quantite = quantite - ? WHERE produit_id = ? AND emplacement = "Hall"', (qte_hall, pid))
                    if qte_kit > 0:
                        lignes.append({'pid': pid, 'qte': qte_kit, 'prix': p['prix_kit'] or p['prix_vente_hall'], 'mt': mt_kit, 'type': 'kit'})
                        conn.execute('UPDATE stocks SET quantite = quantite - ? WHERE produit_id = ? AND emplacement = "Hall"', (qte_kit, pid))
                    if qte_bar > 0:
                        lignes.append({'pid': pid, 'qte': qte_bar, 'prix': p['prix_bar'] or p['prix_vente_hall'], 'mt': mt_bar, 'type': 'bar'})
                        conn.execute('UPDATE stocks SET quantite = quantite - ? WHERE produit_id = ? AND emplacement = "Hall"', (qte_bar, pid))

        if total_vente == 0:
            flash("⚠️ Aucune vente à enregistrer.", "warning"); conn.close(); return redirect(url_for('caisse'))

        pay_especes = float(request.form.get('montant_especes', 0) or 0)
        pay_wave = float(request.form.get('montant_wave', 0) or 0)
        pay_orange = float(request.form.get('montant_orange', 0) or 0)
        
        motif_ecart = request.form.get('motif_ecart', '').strip()
        total_paye = pay_especes + pay_wave + pay_orange
        ecart = total_paye - total_vente
        
        if abs(ecart) > 0 and not motif_ecart:
            flash("⚠️ Un motif est obligatoire en cas d'écart de caisse.", "danger")
            conn.close()
            return redirect(url_for('caisse'))

        modes_paiement = []
        if pay_especes > 0: modes_paiement.append(('especes', pay_especes))
        if pay_wave > 0: modes_paiement.append(('wave', pay_wave))
        if pay_orange > 0: modes_paiement.append(('orange_money', pay_orange))
        
        if not modes_paiement:
            modes_paiement.append(('especes', total_vente))

        premier_mode = True
        for mode, montant_mode in modes_paiement:
            cur = conn.execute('INSERT INTO ventes (date_heure, caissier_id, emplacement_vente, total, mode_paiement, client_id) VALUES (?, 1, "Hall", ?, ?, NULL)', (dh, montant_mode, mode))
            vid = cur.lastrowid
            if premier_mode:
                for l in lignes:
                    conn.execute('INSERT INTO lignes_vente (vente_id, produit_id, quantite, prix_unitaire, montant_kit) VALUES (?, ?, ?, ?, ?)', (vid, l['pid'], l['qte'], l['prix'], l['mt']))
                premier_mode = False

        conn.commit(); conn.close()
        flash(f"✅ Vente enregistrée ! Total: {fmt(total_vente)} FCFA", "success")
        return redirect(url_for('caisse'))

    prods = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = "Hall" ORDER BY nom').fetchall()
    tj = conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = ?', (today,)).fetchone()['v']
    conn.close()
    return render_template('caisse.html', produits=prods, total_jour=tj, date_jour=today, caisse_fermee=caisse_fermee)

# ==========================================
# 3.bis COMMANDES (NOUVEAU)
# ==========================================
@app.route('/commandes', methods=['GET', 'POST'])
@check_access('acces_clients') # On utilise l'accès clients pour les commandes
def commandes():
    conn = get_db()
    
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        if not client_id:
            flash("⚠️ Vous devez sélectionner un client pour une commande.", "danger")
            conn.close()
            return redirect(url_for('commandes'))
            
        dh = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_commande = 0
        lignes = []
        
        for p in conn.execute('SELECT * FROM produits').fetchall():
            pid = p['id']
            qte = int(request.form.get(f'qte_cmd_{pid}', 0) or 0)
            prix = float(request.form.get(f'prix_cmd_{pid}', 0) or 0)
            
            if qte > 0 and prix > 0:
                montant = qte * prix
                total_commande += montant
                lignes.append({'pid': pid, 'qte': qte, 'prix': prix, 'mt': montant})
                # Décrémenter le stock
                conn.execute('UPDATE stocks SET quantite = quantite - ? WHERE produit_id = ? AND emplacement = "Hall"', (qte, pid))
                
        if total_commande == 0:
            flash("⚠️ Aucune commande à enregistrer.", "warning"); conn.close(); return redirect(url_for('commandes'))
            
        # Enregistrer la commande
        cur = conn.execute('INSERT INTO commandes (date_commande, client_id, total, statut, utilisateur_id) VALUES (?, ?, ?, "Impayée", ?)', (dh, client_id, total_commande, session['user_id']))
        cmd_id = cur.lastrowid
        
        # Enregistrer les lignes
        for l in lignes:
            conn.execute('INSERT INTO lignes_commande (commande_id, produit_id, quantite, prix_unitaire, montant) VALUES (?, ?, ?, ?, ?)', (cmd_id, l['pid'], l['qte'], l['prix'], l['mt']))
            
        # Mettre à jour le solde du client
        conn.execute('UPDATE clients SET solde_du = solde_du + ? WHERE id = ?', (total_commande, client_id))
        
        conn.commit(); conn.close()
        flash(f"✅ Commande enregistrée pour {total_commande} FCFA !", "success")
        return redirect(url_for('commandes'))

    prods = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = "Hall" ORDER BY nom').fetchall()
    clients = conn.execute('SELECT * FROM clients ORDER BY nom').fetchall()
    conn.close()
    return render_template('commandes.html', produits=prods, clients=clients)

# ==========================================
# 4. CLÔTURE DE CAISSE
# ==========================================
@app.route('/cloture', methods=['GET', 'POST'])
@check_access('acces_cloture')
def cloture():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    cloture_existante = conn.execute('SELECT * FROM clotures_caisse WHERE date_cloture = ?', (today,)).fetchone()
    if request.method == 'POST' and not cloture_existante:
        theo = conn.execute('SELECT mode_paiement, SUM(total) as total_montant FROM ventes WHERE date(date_heure) = ? AND mode_paiement != "credit" GROUP BY mode_paiement', (today,)).fetchall()
        theo_dict = {t['mode_paiement']: t['total_montant'] for t in theo}
        esp_theo, wave_theo, orange_theo = theo_dict.get('especes', 0), theo_dict.get('wave', 0), theo_dict.get('orange_money', 0)
        total_theo = esp_theo + wave_theo + orange_theo
        esp_reel = float(request.form.get('especes_reel', 0) or 0); wave_reel = float(request.form.get('wave_reel', 0) or 0); orange_reel = float(request.form.get('orange_reel', 0) or 0)
        total_reel = esp_reel + wave_reel + orange_reel
        conn.execute('''INSERT INTO clotures_caisse (date_cloture, heure_cloture, utilisateur_id, especes_theoriques, especes_reelles, ecart_especes, wave_theoriques, wave_reelles, ecart_wave, orange_theoriques, orange_reelles, ecart_orange, total_theorique, total_reel, ecart_total, statut) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cloturee')''', (today, datetime.now().strftime('%H:%M:%S'), session['user_id'], esp_theo, esp_reel, esp_reel - esp_theo, wave_theo, wave_reel, wave_reel - wave_theo, orange_theo, orange_reel, orange_reel - orange_theo, total_theo, total_reel, total_reel - total_theo))
        conn.commit(); conn.close(); flash("✅ Caisse clôturée avec succès !", "success"); return redirect(url_for('cloture'))
    data = {}
    if cloture_existante: data = dict(cloture_existante)
    else:
        theo = conn.execute('SELECT mode_paiement, SUM(total) as total_montant FROM ventes WHERE date(date_heure) = ? AND mode_paiement != "credit" GROUP BY mode_paiement', (today,)).fetchall()
        theo_dict = {t['mode_paiement']: t['total_montant'] for t in theo}
        data = {'especes_theoriques': theo_dict.get('especes', 0), 'wave_theoriques': theo_dict.get('wave', 0), 'orange_theoriques': theo_dict.get('orange_money', 0), 'total_theorique': sum(theo_dict.values()), 'heure_cloture': None}
    conn.close()
    return render_template('cloture.html', data=data, cloture_existante=cloture_existante, date_jour=today)

@app.route('/recu_cloture')
@check_access('acces_cloture')
def recu_cloture():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    c = conn.execute('SELECT * FROM clotures_caisse WHERE date_cloture = ?', (today,)).fetchone()
    u = conn.execute('SELECT nom FROM utilisateurs WHERE id = ?', (c['utilisateur_id'],)).fetchone() if c else None
    conn.close()
    if not c: return "Aucune clôture aujourd'hui.", 404
    html = f"""<html><head><title>Reçu de Clôture</title><style>body{{font-family:Arial;padding:20px;max-width:600px;margin:auto}}h2{{text-align:center;border-bottom:2px solid #333;padding-bottom:10px}}table{{width:100%;border-collapse:collapse;margin-top:20px}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background-color:#f2f2f2}}.total{{font-weight:bold;background-color:#e0e0e0}}.sign{{margin-top:50px;display:flex;justify-content:space-between}}.sign div{{border-top:1px solid #000;width:40%;text-align:center;padding-top:5px}}@media print{{.no-print{{display:none}}}}</style></head><body><h2>REÇU DE CLÔTURE DE CAISSE</h2><p><strong>Date :</strong> {c['date_cloture']}<br><strong>Caissier(ère) :</strong> {u['nom'] if u else 'Inconnu'}<br><strong>Heure :</strong> {c['heure_cloture']}</p><table><tr><th>Mode</th><th>Théorique</th><th>Réel</th><th>Écart</th></tr><tr><td>Espèces</td><td>{fmt(c['especes_theoriques'])}</td><td>{fmt(c['especes_reelles'])}</td><td>{fmt(c['ecart_especes'])}</td></tr><tr><td>Wave</td><td>{fmt(c['wave_theoriques'])}</td><td>{fmt(c['wave_reelles'])}</td><td>{fmt(c['ecart_wave'])}</td></tr><tr><td>Orange Money</td><td>{fmt(c['orange_theoriques'])}</td><td>{fmt(c['orange_reelles'])}</td><td>{fmt(c['ecart_orange'])}</td></tr><tr class="total"><td>TOTAL</td><td>{fmt(c['total_theorique'])}</td><td>{fmt(c['total_reel'])}</td><td>{fmt(c['ecart_total'])}</td></tr></table><div class="sign"><div>Signature Caissier(ère)</div><div>Signature Responsable</div></div><div class="no-print" style="text-align:center;margin-top:30px"><button onclick="window.print()" style="padding:10px 20px;font-size:16px;cursor:pointer">🖨️ Imprimer / PDF</button></div></body></html>"""
    return html

# ==========================================
# 5. APPROVISIONNEMENT
# ==========================================
@app.route('/approvisionnement', methods=['GET', 'POST'])
@check_access('acces_appro')
def approvisionnement():
    conn = get_db()
    if request.method == 'POST':
        date_app = request.form['date_appro']; produit_id = int(request.form['produit_id']); casiers = int(request.form['casiers']); btles_casier = int(request.form['bouteilles_par_casier']); prix_casier = float(request.form['prix_achat_casier']); emplacement = request.form['emplacement']
        total_btles = casiers * btles_casier; cout_unitaire = prix_casier / btles_casier if btles_casier > 0 else 0
        prod = conn.execute('SELECT * FROM produits WHERE id = ?', (produit_id,)).fetchone(); prix_vente = prod['prix_vente_hall']
        marge_unitaire = prix_vente - cout_unitaire; marge_totale = marge_unitaire * total_btles
        conn.execute('''INSERT INTO approvisionnements (date_appro, produit_id, casiers, bouteilles_par_casier, total_bouteilles, prix_achat_casier, cout_unitaire, prix_vente_actuel, marge_unitaire, marge_totale, emplacement) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (date_app, produit_id, casiers, btles_casier, total_btles, prix_casier, cout_unitaire, prix_vente, marge_unitaire, marge_totale, emplacement))
        conn.execute('''INSERT INTO stocks (produit_id, emplacement, quantite) VALUES (?, ?, ?) ON CONFLICT(produit_id, emplacement) DO UPDATE SET quantite = quantite + ?''', (produit_id, emplacement, total_btles, total_btles))
        conn.execute('UPDATE produits SET prix_achat = ? WHERE id = ?', (cout_unitaire, produit_id))
        conn.commit(); conn.close(); flash(f"✅ Approvisionnement enregistré ! Marge totale : {fmt(marge_totale)} FCFA", "success"); return redirect(url_for('approvisionnement'))
    date_debut = request.args.get('date_debut', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')); date_fin = request.args.get('date_fin', datetime.now().strftime('%Y-%m-%d'))
    appros = conn.execute('SELECT a.*, p.nom as produit_nom, p.categorie, p.prix_vente_hall as prix_vente_actuel_fiche FROM approvisionnements a JOIN produits p ON a.produit_id = p.id WHERE a.date_appro BETWEEN ? AND ? ORDER BY a.date_appro DESC', (date_debut, date_fin)).fetchall()
    kpis = conn.execute('SELECT SUM(a.prix_achat_casier * a.casiers) as total_investi, SUM(a.marge_totale) as marge_brute, SUM(a.total_bouteilles) as total_bouteilles FROM approvisionnements a WHERE a.date_appro BETWEEN ? AND ?', (date_debut, date_fin)).fetchone()
    produits = conn.execute('SELECT * FROM produits ORDER BY categorie, nom').fetchall(); conn.close()
    return render_template('approvisionnement.html', appros=appros, produits=produits, kpis=kpis, date_debut=date_debut, date_fin=date_fin)

# ==========================================
# 6. HISTORIQUE
# ==========================================
@app.route('/historique')
@check_access('acces_historique')
def historique():
    conn = get_db()
    db = request.args.get('date_debut', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')); df = request.args.get('date_fin', datetime.now().strftime('%Y-%m-%d')); mf = request.args.get('mode', '')
    q = '''SELECT v.id, v.date_heure, v.total, v.mode_paiement, c.nom as client_nom, COUNT(lv.id) as nb_produits FROM ventes v LEFT JOIN clients c ON v.client_id = c.id LEFT JOIN lignes_vente lv ON v.id = lv.vente_id WHERE date(v.date_heure) BETWEEN ? AND ?'''
    p = [db, df]
    if mf: q += ' AND v.mode_paiement = ?'; p.append(mf)
    q += ' GROUP BY v.id ORDER BY v.date_heure DESC'
    ventes = conn.execute(q, p).fetchall(); conn.close()
    return render_template('historique.html', ventes=ventes, date_debut=db, date_fin=df, mode_filtre=mf, total_ventes=sum(v['total'] for v in ventes), nb_ventes=len(ventes))

# ==========================================
# 7. CLIENTS
# ==========================================
@app.route('/clients', methods=['GET', 'POST'])
@check_access('acces_clients')
def clients():
    conn = get_db()
    if request.method == 'POST':
        conn.execute('INSERT INTO clients (nom, telephone, adresse, solde_du, plafond_credit) VALUES (?, ?, ?, 0, ?)', (request.form['nom'], request.form['telephone'], request.form.get('adresse', ''), float(request.form['plafond'] or 0)))
        conn.commit(); conn.close(); flash("✅ Client créé !", "success"); return redirect(url_for('clients'))
    lc = conn.execute('SELECT c.*, MAX(v.date_heure) as derniere_commande FROM clients c LEFT JOIN ventes v ON c.id = v.client_id GROUP BY c.id ORDER BY c.nom').fetchall(); conn.close()
    return render_template('clients.html', clients=lc)

# ==========================================
# 8. PAIEMENTS
# ==========================================
@app.route('/paiements', methods=['GET', 'POST'])
@check_access('acces_paiements')
def paiements():
    conn = get_db()
    if request.method == 'POST':
        dp = request.form['date_paiement']
        for m, k in [('especes', 'montant_especes'), ('wave', 'montant_wave'), ('orange_money', 'montant_orange')]:
            v = request.form.get(k, 0)
            if float(v) > 0: conn.execute('INSERT INTO paiements (date_paiement, mode_paiement, montant) VALUES (?, ?, ?)', (dp, m, v))
        conn.commit(); conn.close(); flash("✅ Paiements enregistrés !", "success"); return redirect(url_for('paiements'))
    today = datetime.now().strftime('%Y-%m-%d')
    stats = conn.execute('SELECT mode_paiement, SUM(montant) as total_montant FROM paiements WHERE date(date_paiement) = ? GROUP BY mode_paiement', (today,)).fetchall()
    hist = conn.execute('SELECT * FROM paiements WHERE date(date_paiement) = ? ORDER BY id DESC', (today,)).fetchall(); conn.close()
    return render_template('paiements.html', stats=stats, historique=hist, date_jour=today)

# ==========================================
# 9. INVENTAIRE
# ==========================================
@app.route('/inventaire', methods=['GET', 'POST'])
@check_access('acces_inventaire')
def inventaire():
    conn = get_db()
    if request.method == 'POST':
        emp, di, note = request.form['emplacement'], request.form['date_inventaire'], request.form.get('note', '')
        cur = conn.execute('INSERT INTO inventaires (date_inventaire, emplacement, note, utilisateur_id) VALUES (?, ?, ?, ?)', (di, emp, note, session['user_id'])); iid = cur.lastrowid; te = 0
        for k, v in request.form.items():
            if k.startswith('stock_physique_') and v:
                pid, sp = int(k.replace('stock_physique_', '')), int(v)
                st = conn.execute('SELECT COALESCE(quantite, 0) FROM stocks WHERE produit_id = ? AND emplacement = ?', (pid, emp)).fetchone()[0]; ec = sp - st; te += ec
                conn.execute('INSERT INTO lignes_inventaire (inventaire_id, produit_id, stock_theorique, stock_physique, ecart) VALUES (?, ?, ?, ?, ?)', (iid, pid, st, sp, ec))
                conn.execute('UPDATE stocks SET quantite = ? WHERE produit_id = ? AND emplacement = ?', (sp, pid, emp))
        conn.commit(); conn.close(); flash(f"{'⚠️' if te != 0 else '✅'} Inventaire validé ! Écart: {te}", "warning" if te!=0 else "success"); return redirect(url_for('inventaire'))
    emp = request.args.get('emplacement', 'Hall')
    prods = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_theorique FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = ? ORDER BY p.categorie, p.nom', (emp,)).fetchall()
    hist = conn.execute('SELECT i.*, u.nom as utilisateur_nom, COUNT(li.id) as nb_lignes, SUM(li.ecart) as total_ecart FROM inventaires i LEFT JOIN utilisateurs u ON i.utilisateur_id = u.id LEFT JOIN lignes_inventaire li ON i.id = li.inventaire_id GROUP BY i.id ORDER BY i.date_inventaire DESC').fetchall(); conn.close()
    return render_template('inventaire.html', produits=prods, emplacement=emp, historique=hist, date_jour=datetime.now().strftime('%Y-%m-%d'))

@app.route('/export_inventaire/<fmt>')
@check_access('acces_inventaire')
def export_inventaire(fmt):
    emp = request.args.get('emplacement', 'Hall'); di = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    prods = conn.execute('SELECT p.nom, p.categorie, COALESCE(s.quantite, 0) as stock_theorique FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = ? ORDER BY p.categorie, p.nom', (emp,)).fetchall(); conn.close()
    if fmt == 'excel':
        df = pd.DataFrame([{'Produit': p['nom'], 'Catégorie': p['categorie'], 'Stock Théorique': p['stock_theorique'], 'Stock Physique': '', 'Écart': '', 'Observation': ''} for p in prods])
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False, sheet_name='Inventaire')
        out.seek(0); return send_file(out, as_attachment=True, download_name=f'inventaire_{emp}_{di}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    elif fmt == 'csv':
        out = io.StringIO("Produit;Catégorie;Stock Théorique;Stock Physique;Écart;Observation\n")
        for p in prods: out.write(f"{p['nom']};{p['categorie']};{p['stock_theorique']};;;\n")
        r = make_response(out.getvalue()); r.headers['Content-Type'] = 'text/csv; charset=utf-8'; r.headers['Content-Disposition'] = f'attachment; filename=inventaire_{emp}_{di}.csv'; return r
    return "Format non supporté", 400

if __name__ == '__main__':
    app.run(debug=True)