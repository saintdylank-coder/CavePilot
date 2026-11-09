from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, make_response
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import pandas as pd
import os
import io
import secrets
import re
from dotenv import load_dotenv
from flask_talisman import Talisman
import psycopg2
from psycopg2.extras import RealDictCursor

# ==========================================
# 🔐 CONFIGURATION SÉCURITÉ & ENVIRONNEMENT
# ==========================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
CODE_MAITRE = os.getenv('CODE_MAITRE', 'PATRON2026')

Talisman(app, force_https=False, session_cookie_secure=True, content_security_policy=None)

SESSION_TIMEOUT = timedelta(minutes=30)
MAX_TENTATIVES = 5
BLOCAGE_DUREE = timedelta(minutes=15)
MDP_LONGUEUR_MIN = 8
MDP_REQUIERT_MAJUSCULE = True
MDP_REQUIERT_CHIFFRE = True

# ==========================================
# 🔧 ADAPTATEUR DE BASE DE DONNÉES
# ==========================================

class PGDB:
    def __init__(self):
        self.conn = psycopg2.connect(os.getenv('DATABASE_URL'), cursor_factory=RealDictCursor)
    
    def execute(self, query, params=None):
        cur = self.conn.cursor()
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        return cur
    
    def commit(self):
        self.conn.commit()
    
    def close(self):
        self.conn.close()

def get_db():
    return PGDB()

# ==========================================
# 🗄️ CRÉATION AUTOMATIQUE DES TABLES FACTURES
# ==========================================
def init_factures_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS factures (
            id SERIAL PRIMARY KEY,
            numero VARCHAR(20) UNIQUE NOT NULL,
            client_nom VARCHAR(100) DEFAULT 'Anonyme',
            date_ouverture TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_fermeture TIMESTAMP,
            statut VARCHAR(20) DEFAULT 'ouverte',
            total_general FLOAT DEFAULT 0,
            total_paye FLOAT DEFAULT 0,
            reste_a_payer FLOAT DEFAULT 0,
            utilisateur_id INTEGER,
            notes TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lignes_facture (
            id SERIAL PRIMARY KEY,
            facture_id INTEGER REFERENCES factures(id) ON DELETE CASCADE,
            produit_id INTEGER,
            produit_nom VARCHAR(100),
            categorie VARCHAR(50),
            quantite INTEGER,
            prix_unitaire FLOAT,
            montant FLOAT,
            date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS paiements_facture (
            id SERIAL PRIMARY KEY,
            facture_id INTEGER REFERENCES factures(id) ON DELETE CASCADE,
            montant FLOAT,
            mode_paiement VARCHAR(20),
            date_paiement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            utilisateur_id INTEGER,
            notes TEXT
        )''')
        conn.commit()
        print("✅ Tables factures vérifiées/créées")
    except Exception as e:
        print(f"⚠️ Erreur création tables factures: {e}")
    finally:
        conn.close()

init_factures_tables()

# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================

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

def get_client_ip():
    return request.remote_addr or 'inconnue'

def verifier_mot_de_passe_fort(mdp):
    if len(mdp) < MDP_LONGUEUR_MIN:
        return False, f"Le mot de passe doit faire au moins {MDP_LONGUEUR_MIN} caractères."
    if MDP_REQUIERT_MAJUSCULE and not re.search(r'[A-Z]', mdp):
        return False, "Le mot de passe doit contenir au moins une majuscule."
    if MDP_REQUIERT_CHIFFRE and not re.search(r'[0-9]', mdp):
        return False, "Le mot de passe doit contenir au moins un chiffre."
    return True, "OK"

def est_compte_bloque(nom_utilisateur):
    conn = get_db()
    depuis = (datetime.now() - BLOCAGE_DUREE).strftime('%Y-%m-%d %H:%M:%S')
    nb_echecs = conn.execute('SELECT COUNT(*) as c FROM tentatives_connexion WHERE nom_utilisateur = %s AND date_tentative > %s AND succes = 0', (nom_utilisateur, depuis)).fetchone()['c']
    conn.close()
    return nb_echecs >= MAX_TENTATIVES

def enregistrer_tentative(nom_utilisateur, succes):
    conn = get_db()
    conn.execute('INSERT INTO tentatives_connexion (nom_utilisateur, ip_adresse, date_tentative, succes) VALUES (%s, %s, %s, %s)', (nom_utilisateur, get_client_ip(), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if succes else 0))
    conn.commit(); conn.close()

def enregistrer_connexion(user_id, nom, succes, motif_echec=None):
    conn = get_db()
    conn.execute('INSERT INTO journal_connexions (utilisateur_id, nom_utilisateur, ip_adresse, date_connexion, succes, motif_echec) VALUES (%s, %s, %s, %s, %s, %s)', (user_id, nom, get_client_ip(), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if succes else 0, motif_echec))
    conn.commit(); conn.close()

def enregistrer_action(action, table_concernee=None, enregistrement_id=None, details=None):
    if 'user_id' not in session: return
    conn = get_db()
    conn.execute('INSERT INTO journal_actions (utilisateur_id, nom_utilisateur, action, table_concernee, enregistrement_id, details, ip_adresse, date_action) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (session['user_id'], session.get('user_nom', 'Inconnu'), action, table_concernee, enregistrement_id, details, get_client_ip(), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit(); conn.close()

def verifier_session_active():
    if 'user_id' in session and 'derniere_activite' in session:
        if datetime.now() - datetime.fromisoformat(session['derniere_activite']) > SESSION_TIMEOUT:
            session.clear(); flash("⏰ Session expirée pour inactivité.", "warning"); return False
    if 'user_id' in session: session['derniere_activite'] = datetime.now().isoformat()
    return True

def check_access(acces_key):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session: flash("⚠️ Vous devez vous connecter.", "warning"); return redirect(url_for('connexion'))
            if not verifier_session_active(): return redirect(url_for('connexion'))
            if not session.get(acces_key): flash(f"⛔ Accès non autorisé.", "danger"); return redirect(url_for('dashboard'))
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
        if est_compte_bloque(nom):
            flash(f"🔒 Compte bloqué. Réessayez dans {BLOCAGE_DUREE.seconds // 60} min.", "danger")
            return render_template('connexion.html')
        conn = get_db()
        user = conn.execute('SELECT * FROM utilisateurs WHERE nom = %s AND mot_de_passe = %s AND actif = 1', (nom, hash_password(mdp))).fetchone()
        if user:
            enregistrer_tentative(nom, True); enregistrer_connexion(user['id'], nom, True)
            acces = {k: bool(user.get(f'acces_{k}', 0)) for k in ['dashboard', 'saisie', 'cloture', 'appro', 'historique', 'clients', 'paiements', 'inventaire', 'comptes', 'produits', 'commandes']}
            if not any(acces.values()): conn.close(); flash("⛔ Aucune autorisation.", "danger"); return render_template('connexion.html')
            session['user_id'], session['user_nom'], session['user_role'] = user['id'], user['nom'], user['role']
            session['derniere_activite'] = datetime.now().isoformat()
            for k, v in acces.items(): session[f'acces_{k}'] = v
            conn.close(); flash(f"✅ Bienvenue {user['nom']} !", "success")
            return redirect(url_for('dashboard'))
        else:
            enregistrer_tentative(nom, False); conn.close(); flash("❌ Identifiants incorrects.", "danger")
    return render_template('connexion.html')

@app.route('/deconnexion')
def deconnexion():
    if 'user_id' in session: enregistrer_connexion(session['user_id'], session.get('user_nom'), True); enregistrer_action("Déconnexion")
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
        nom, role, mdp, mdp2 = request.form['nom'].strip(), request.form['role'], request.form['mot_de_passe'], request.form.get('confirmation_mdp', '')
        jours = ','.join(request.form.getlist('jours'))
        acces = {k: 1 if request.form.get(k) else 0 for k in ['acces_dashboard', 'acces_saisie', 'acces_cloture', 'acces_appro', 'acces_historique', 'acces_clients', 'acces_paiements', 'acces_inventaire', 'acces_comptes', 'acces_produits', 'acces_commandes']}
        ok, msg = verifier_mot_de_passe_fort(mdp)
        if not ok: flash(f"⚠️ {msg}", "danger"); conn.close(); return redirect(url_for('comptes'))
        if mdp != mdp2: flash("⚠️ Mots de passe différents.", "danger"); conn.close(); return redirect(url_for('comptes'))
        if conn.execute('SELECT id FROM utilisateurs WHERE nom = %s', (nom,)).fetchone(): flash("⚠️ Utilisateur existe déjà.", "warning"); conn.close(); return redirect(url_for('comptes'))
        conn.execute('INSERT INTO utilisateurs (nom, role, mot_de_passe, jours_travail, actif, acces_dashboard, acces_saisie, acces_cloture, acces_appro, acces_historique, acces_clients, acces_paiements, acces_inventaire, acces_comptes, acces_produits, acces_commandes) VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (nom, role, hash_password(mdp), jours, acces['acces_dashboard'], acces['acces_saisie'], acces['acces_cloture'], acces['acces_appro'], acces['acces_historique'], acces['acces_clients'], acces['acces_paiements'], acces['acces_inventaire'], acces['acces_comptes'], acces['acces_produits'], acces['acces_commandes']))
        conn.commit(); conn.close(); flash("✅ Compte créé !", "success"); return redirect(url_for('comptes'))
    users = conn.execute('SELECT * FROM utilisateurs ORDER BY nom').fetchall(); conn.close()
    return render_template('comptes.html', utilisateurs=users)

@app.route('/desactiver_compte/<int:uid>')
@check_access('acces_comptes')
def desactiver_compte(uid):
    conn = get_db()
    user = conn.execute('SELECT nom FROM utilisateurs WHERE id = %s', (uid,)).fetchone()
    conn.execute('UPDATE utilisateurs SET actif = 0 WHERE id = %s', (uid,)); conn.commit(); conn.close()
    enregistrer_action("Désactivation de compte", "utilisateurs", uid, f"Compte '{user['nom']}' désactivé")
    return redirect(url_for('comptes'))

@app.route('/reactiver_compte/<int:uid>')
@check_access('acces_comptes')
def reactiver_compte(uid):
    conn = get_db()
    user = conn.execute('SELECT nom FROM utilisateurs WHERE id = %s', (uid,)).fetchone()
    conn.execute('UPDATE utilisateurs SET actif = 1 WHERE id = %s', (uid,)); conn.commit(); conn.close()
    enregistrer_action("Réactivation de compte", "utilisateurs", uid, f"Compte '{user['nom']}' réactivé")
    return redirect(url_for('comptes'))

@app.route('/supprimer_compte/<int:uid>')
@check_access('acces_comptes')
def supprimer_compte(uid):
    conn = get_db()
    if uid == session.get('user_id'): flash("⚠️ Vous ne pouvez pas supprimer votre propre compte.", "warning")
    else:
        user = conn.execute('SELECT nom FROM utilisateurs WHERE id = %s', (uid,)).fetchone()
        conn.execute('DELETE FROM utilisateurs WHERE id = %s', (uid,)); conn.commit()
        flash("✅ Compte supprimé.", "success")
    conn.close(); return redirect(url_for('comptes'))

@app.route('/modifier_autorisations/<int:uid>', methods=['GET', 'POST'])
@check_access('acces_comptes')
def modifier_autorisations(uid):
    conn = get_db()
    user = conn.execute('SELECT * FROM utilisateurs WHERE id = %s', (uid,)).fetchone()
    if request.method == 'POST':
        acces = {k: 1 if request.form.get(k) else 0 for k in ['acces_dashboard', 'acces_saisie', 'acces_cloture', 'acces_appro', 'acces_historique', 'acces_clients', 'acces_paiements', 'acces_inventaire', 'acces_comptes', 'acces_produits', 'acces_commandes']}
        conn.execute('UPDATE utilisateurs SET acces_dashboard=%s, acces_saisie=%s, acces_cloture=%s, acces_appro=%s, acces_historique=%s, acces_clients=%s, acces_paiements=%s, acces_inventaire=%s, acces_comptes=%s, acces_produits=%s, acces_commandes=%s WHERE id=%s', (acces['acces_dashboard'], acces['acces_saisie'], acces['acces_cloture'], acces['acces_appro'], acces['acces_historique'], acces['acces_clients'], acces['acces_paiements'], acces['acces_inventaire'], acces['acces_comptes'], acces['acces_produits'], acces['acces_commandes'], uid))
        conn.commit(); conn.close()
        enregistrer_action("Modification autorisations", "utilisateurs", uid, f"Autorisations de '{user['nom']}' modifiées")
        flash("✅ Autorisations mises à jour !", "success"); return redirect(url_for('comptes'))
    conn.close()
    return render_template('modifier_autorisations.html', user=user)

@app.route('/creer_compte', methods=['GET', 'POST'])
def creer_compte():
    if 'user_id' in session: return redirect(url_for('comptes'))
    if request.method == 'POST':
        try:
            code_maitre = request.form.get('code_maitre', '').strip()
            if code_maitre != CODE_MAITRE: flash("❌ Code maître incorrect.", "danger"); return render_template('creer_compte.html', code_valide=False)
            nom, role, mdp, mdp2 = request.form.get('nom', '').strip(), request.form.get('role', '').strip(), request.form.get('mot_de_passe', ''), request.form.get('confirmation_mdp', '')
            jours = ','.join(request.form.getlist('jours'))
            if not nom or not role or not mdp: flash("⚠️ Tous les champs obligatoires doivent être remplis.", "warning"); return render_template('creer_compte.html', code_valide=True)
            ok, msg = verifier_mot_de_passe_fort(mdp)
            if not ok: flash(f"⚠️ {msg}", "warning"); return render_template('creer_compte.html', code_valide=True)
            if mdp != mdp2: flash("⚠️ Les mots de passe ne correspondent pas.", "warning"); return render_template('creer_compte.html', code_valide=True)
            conn = get_db()
            if conn.execute('SELECT id FROM utilisateurs WHERE nom = %s', (nom,)).fetchone(): flash("⚠️ Ce nom existe déjà.", "warning"); conn.close(); return render_template('creer_compte.html', code_valide=True)
            nb_users = conn.execute('SELECT COUNT(*) as c FROM utilisateurs').fetchone()['c']
            if nb_users == 0:
                acces = {k: 1 for k in ['acces_dashboard', 'acces_saisie', 'acces_cloture', 'acces_appro', 'acces_historique', 'acces_clients', 'acces_paiements', 'acces_inventaire', 'acces_comptes', 'acces_produits', 'acces_commandes']}
                role_final = 'Administrateur'
            else:
                acces = {k: 1 if request.form.get(k) else 0 for k in ['acces_dashboard', 'acces_saisie', 'acces_cloture', 'acces_appro', 'acces_historique', 'acces_clients', 'acces_paiements', 'acces_inventaire', 'acces_comptes', 'acces_produits', 'acces_commandes']}
                role_final = role
            conn.execute('INSERT INTO utilisateurs (nom, role, mot_de_passe, jours_travail, actif, acces_dashboard, acces_saisie, acces_cloture, acces_appro, acces_historique, acces_clients, acces_paiements, acces_inventaire, acces_comptes, acces_produits, acces_commandes) VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (nom, role_final, hash_password(mdp), jours, acces['acces_dashboard'], acces['acces_saisie'], acces['acces_cloture'], acces['acces_appro'], acces['acces_historique'], acces['acces_clients'], acces['acces_paiements'], acces['acces_inventaire'], acces['acces_comptes'], acces['acces_produits'], acces['acces_commandes']))
            conn.commit(); conn.close()
            enregistrer_action("Création de compte", "utilisateurs", details=f"Compte '{nom}' créé")
            flash(f"✅ Compte {nom} créé !", "success"); return redirect(url_for('connexion'))
        except Exception as e: flash(f"❌ Erreur : {str(e)}", "danger"); return render_template('creer_compte.html', code_valide=True)
    return render_template('creer_compte.html', code_valide=False)

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
        'stock_hall': conn.execute('SELECT COALESCE(SUM(quantite), 0) as s FROM stocks WHERE emplacement=%s', ('Hall',)).fetchone()['s'],
        'valeur_stock': fmt(conn.execute('SELECT COALESCE(SUM(s.quantite * p.prix_vente_hall), 0) as v FROM stocks s JOIN produits p ON s.produit_id = p.id WHERE s.emplacement=%s', ('Hall',)).fetchone()['v']),
        'total_credits': fmt(conn.execute('SELECT COALESCE(SUM(solde_du), 0) as c FROM clients').fetchone()['c']),
        'total_clients': conn.execute('SELECT COUNT(*) as c FROM clients').fetchone()['c'],
        'ventes_jour': conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = %s', (today,)).fetchone()['v'],
        'ventes_mois': fmt(conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE to_char(date_heure, %s) = %s', ('YYYY-MM', mois)).fetchone()['v']),
    }
    stats['marge_mois'] = fmt(conn.execute('SELECT COALESCE(SUM(marge_totale), 0) as total FROM approvisionnements WHERE to_char(date_appro, %s) = %s', ('YYYY-MM', mois)).fetchone()['total'])
    total_rembourse = conn.execute('SELECT COALESCE(SUM(montant), 0) as total FROM remboursements').fetchone()['total']
    credits_encours = conn.execute('SELECT COALESCE(SUM(solde_du), 0) as total FROM clients WHERE solde_du > 0').fetchone()['total']
    total_vendu_credit = total_rembourse + credits_encours
    stats['taux_recouvrement'] = round((total_rembourse / total_vendu_credit) * 100, 1) if total_vendu_credit > 0 else 0
    stats['total_vendu_credit'], stats['total_rembourse'] = fmt(total_vendu_credit), fmt(total_rembourse)
    stats['total_ecarts_today'] = fmt(conn.execute('SELECT COALESCE(SUM(montant_ecart), 0) as total FROM ecarts_caisse WHERE date_ecart = %s', (today,)).fetchone()['total'])
    
    labels_jours, data_ventes = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        labels_jours.append((datetime.now() - timedelta(days=i)).strftime('%d/%m'))
        data_ventes.append(conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = %s', (d,)).fetchone()['v'])
    
    stats_paiement = conn.execute('SELECT mode_paiement, SUM(total) as total_montant FROM ventes WHERE to_char(date_heure, %s) = %s GROUP BY mode_paiement', ('YYYY-MM', mois)).fetchall()
    total_gen = sum(s['total_montant'] for s in stats_paiement)
    labels_p, data_p, couleurs_p = [], [], []
    cmap = {'especes': '#000000', 'wave': '#D4AF37', 'orange_money': '#B8860B', 'credit': '#dc3545'}
    for s in stats_paiement:
        pct = round((s['total_montant'] / total_gen * 100), 1) if total_gen > 0 else 0
        labels_p.append(f"{s['mode_paiement'].replace('_', ' ').title()} ({pct}%)"); data_p.append(s['total_montant']); couleurs_p.append(cmap.get(s['mode_paiement'], '#6c757d'))
    
    top_cats = conn.execute('SELECT p.categorie, SUM(lv.montant_kit) as total_ca FROM lignes_vente lv JOIN produits p ON lv.produit_id = p.id JOIN ventes v ON lv.vente_id = v.id WHERE to_char(v.date_heure, %s) = %s GROUP BY p.categorie ORDER BY total_ca DESC LIMIT 3', ('YYYY-MM', mois)).fetchall()
    top_cats_data = []
    for c in top_cats:
        prods = conn.execute('SELECT p.nom, SUM(lv.quantite) as total_qte, SUM(lv.montant_kit) as total_ca FROM lignes_vente lv JOIN produits p ON lv.produit_id = p.id JOIN ventes v ON lv.vente_id = v.id WHERE p.categorie = %s AND to_char(v.date_heure, %s) = %s GROUP BY p.id ORDER BY total_ca DESC LIMIT 5', (c['categorie'], 'YYYY-MM', mois)).fetchall()
        top_cats_data.append({'categorie': c['categorie'], 'total_ca': c['total_ca'], 'produits': prods})
    
    top_ventes = conn.execute('SELECT p.id, SUM(lv.quantite) as total_vendu FROM lignes_vente lv JOIN ventes v ON lv.vente_id = v.id JOIN produits p ON lv.produit_id = p.id WHERE to_char(v.date_heure, %s) = %s GROUP BY p.id ORDER BY total_vendu DESC LIMIT 20', ('YYYY-MM', mois)).fetchall()
    top_ventes_dict = {row['id']: row['total_vendu'] for row in top_ventes}
    max_ventes = max(top_ventes_dict.values()) if top_ventes_dict else 1
    
    alertes_stock_raw = conn.execute('SELECT p.id, p.nom, p.categorie, s.quantite, p.seuil_alerte FROM stocks s JOIN produits p ON s.produit_id = p.id WHERE s.emplacement = %s AND s.quantite <= p.seuil_alerte ORDER BY p.categorie', ('Hall',)).fetchall()
    alertes_par_categorie = {'AUTRES': [], 'VINS': [], 'CHAMPAGNES': []}
    for a in alertes_stock_raw:
        cat = a['categorie'] or 'AUTRES'
        if cat in alertes_par_categorie:
            vendu = top_ventes_dict.get(a['id'], 0); ratio = vendu / max_ventes if max_ventes > 0 else 0
            criticite, ordre = ('critique', 1) if ratio >= 0.5 else (('important', 2) if ratio >= 0.2 else ('faible', 3))
            alertes_par_categorie[cat].append({'id': a['id'], 'nom': a['nom'], 'quantite': a['quantite'], 'seuil_alerte': a['seuil_alerte'], 'total_vendu': vendu, 'criticite': criticite, 'ordre_criticite': ordre})
    for cat in alertes_par_categorie: alertes_par_categorie[cat].sort(key=lambda x: (x['ordre_criticite'], -x['total_vendu']))
    
    date_debut_ecart = request.args.get('date_debut_ecart', today)
    date_fin_ecart = request.args.get('date_fin_ecart', today)
    ecarts = conn.execute('SELECT e.*, u.nom as utilisateur_nom FROM ecarts_caisse e LEFT JOIN utilisateurs u ON e.utilisateur_id = u.id WHERE e.date_ecart BETWEEN %s AND %s ORDER BY e.date_ecart DESC, e.heure_ecart DESC', (date_debut_ecart, date_fin_ecart)).fetchall()
    total_manques = conn.execute('SELECT COALESCE(SUM(montant_ecart), 0) as total FROM ecarts_caisse WHERE date_ecart BETWEEN %s AND %s AND montant_ecart < 0', (date_debut_ecart, date_fin_ecart)).fetchone()['total']
    total_surplus = conn.execute('SELECT COALESCE(SUM(montant_ecart), 0) as total FROM ecarts_caisse WHERE date_ecart BETWEEN %s AND %s AND montant_ecart > 0', (date_debut_ecart, date_fin_ecart)).fetchone()['total']
    
    conn.close()
    return render_template('dashboard.html', date_jour=datetime.now().strftime('%d/%m/%Y'), labels_jours=labels_jours, data_ventes=data_ventes, labels_paiement=labels_p, data_paiement=data_p, couleurs_paiement=couleurs_p, top_cats_data=top_cats_data, alertes_par_categorie=alertes_par_categorie, ecarts=ecarts, date_debut_ecart=date_debut_ecart, date_fin_ecart=date_fin_ecart, total_manques=total_manques, total_surplus=total_surplus, **stats)

# ==========================================
# 📄 SYSTÈME DE FACTURES CLIENT (NOUVEAU - PAGE UNIQUE)
# ==========================================

@app.route('/factures')
@check_access('acces_saisie')
def factures():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    recherche = request.args.get('recherche', '')
    filtre_date = request.args.get('filtre_date', 'aujourd')  # aujourd, semaine, mois, tout
    
    # Construire la clause de filtre de date
    clause_date = ""
    params_date = []
    if filtre_date == 'aujourd':
        clause_date = "AND date(f.date_ouverture) = %s"
        params_date = [today]
    elif filtre_date == 'semaine':
        clause_date = "AND f.date_ouverture >= %s"
        params_date = [(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')]
    elif filtre_date == 'mois':
        clause_date = "AND to_char(f.date_ouverture, 'YYYY-MM') = %s"
        params_date = [today[:7]]
    
    # Récupérer toutes les factures avec leur statut de paiement
    query = f'''
        SELECT f.*, 
               (SELECT COUNT(*) FROM lignes_facture WHERE facture_id = f.id) as nb_produits,
               CASE 
                   WHEN f.reste_a_payer = 0 AND f.total_general > 0 THEN 'soldée'
                   WHEN f.total_paye > 0 AND f.reste_a_payer > 0 THEN 'partielle'
                   WHEN f.total_paye = 0 AND f.total_general > 0 THEN 'impayée'
                   ELSE 'vide'
               END as etat_paiement
        FROM factures f 
        WHERE 1=1 {clause_date}
    '''
    if recherche:
        query += " AND (f.client_nom ILIKE %s OR f.numero ILIKE %s)"
        params_date.extend([f'%{recherche}%', f'%{recherche}%'])
    query += " ORDER BY f.date_ouverture DESC"
    
    toutes_factures = conn.execute(query, params_date).fetchall()
    
    # Séparer par état
    factures_en_cours = [f for f in toutes_factures if f['etat_paiement'] in ('vide', 'impayée', 'partielle')]
    factures_soldées = [f for f in toutes_factures if f['etat_paiement'] == 'soldée']
    
    # Totaux
    total_encaisse_jour = conn.execute('SELECT COALESCE(SUM(total_paye), 0) as total FROM factures WHERE date(date_fermeture) = %s AND statut = %s', (today, 'soldée')).fetchone()['total']
    total_encours = conn.execute('SELECT COALESCE(SUM(reste_a_payer), 0) as total FROM factures WHERE statut = %s', ('ouverte',)).fetchone()['total']
    
    conn.close()
    return render_template('factures.html', 
                          factures_en_cours=factures_en_cours,
                          factures_soldées=factures_soldées,
                          total_encaisse_jour=fmt(total_encaisse_jour),
                          total_encours=fmt(total_encours),
                          recherche=recherche,
                          filtre_date=filtre_date,
                          date_jour=datetime.now().strftime('%d/%m/%Y'))

@app.route('/facture/creer', methods=['POST'])
@check_access('acces_saisie')
def facture_creer():
    """Créer une nouvelle facture rapidement"""
    client_nom = request.form.get('client_nom', 'Anonyme').strip() or 'Anonyme'
    conn = get_db()
    today = datetime.now().strftime('%Y%m%d')
    dernier = conn.execute("SELECT numero FROM factures WHERE numero LIKE %s ORDER BY id DESC LIMIT 1", (f"F{today}%",)).fetchone()
    num = (int(dernier['numero'][-3:]) + 1) if dernier else 1
    numero = f"F{today}{num:03d}"
    
    conn.execute('INSERT INTO factures (numero, client_nom, statut, utilisateur_id) VALUES (%s, %s, %s, %s)', 
                 (numero, client_nom, 'ouverte', session['user_id']))
    conn.commit()
    facture = conn.execute('SELECT id FROM factures WHERE numero = %s', (numero,)).fetchone()
    conn.close()
    flash(f"✅ Facture {numero} créée pour {client_nom}", "success")
    return redirect(url_for('factures'))

@app.route('/facture/<int:facture_id>/detail')
@check_access('acces_saisie')
def facture_detail(facture_id):
    """Retourne le contenu du modal avec les produits disponibles"""
    conn = get_db()
    facture = conn.execute('SELECT * FROM factures WHERE id = %s', (facture_id,)).fetchone()
    if not facture:
        conn.close(); return "<div class='alert alert-danger'>Facture introuvable</div>", 404
    
    lignes = conn.execute('SELECT * FROM lignes_facture WHERE facture_id = %s ORDER BY date_ajout DESC', (facture_id,)).fetchall()
    paiements = conn.execute('SELECT p.*, u.nom as utilisateur_nom FROM paiements_facture p LEFT JOIN utilisateurs u ON p.utilisateur_id = u.id WHERE p.facture_id = %s ORDER BY p.date_paiement DESC', (facture_id,)).fetchall()
    
    # Récupérer les produits disponibles pour l'ajout (uniquement si non verrouillée)
    produits_disponibles = []
    if facture['statut'] != 'soldée':
        produits_disponibles = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s ORDER BY p.categorie, p.nom', ('Hall',)).fetchall()
    
    verrouillee = facture['statut'] == 'soldée'
    conn.close()
    
    return render_template('facture_modal.html', 
                          facture=facture, 
                          lignes=lignes, 
                          paiements=paiements,
                          produits_disponibles=produits_disponibles,
                          verrouillee=verrouillee)
    
    # Déterminer si la facture est verrouillée
    verrouillee = facture['statut'] == 'soldée'
    
    return render_template('facture_modal.html', 
                          facture=facture, 
                          lignes=lignes, 
                          paiements=paiements,
                          verrouillee=verrouillee)

@app.route('/facture/<int:facture_id>/ajouter', methods=['POST'])
@check_access('acces_saisie')
def facture_ajouter(facture_id):
    """Ajouter des produits à une facture"""
    conn = get_db()
    facture = conn.execute('SELECT * FROM factures WHERE id = %s', (facture_id,)).fetchone()
    if not facture or facture['statut'] == 'soldée':
        flash("❌ Facture introuvable ou déjà soldée (verrouillée)", "danger"); conn.close()
        return redirect(url_for('factures'))
    
    total_ajout = 0
    produits_ajoutes = []
    for key, value in request.form.items():
        if key.startswith('qte_') and value and int(value) > 0:
            produit_id = int(key.replace('qte_', ''))
            qte = int(value)
            produit = conn.execute('SELECT * FROM produits WHERE id = %s', (produit_id,)).fetchone()
            if produit:
                montant = qte * produit['prix_vente_hall']
                total_ajout += montant
                conn.execute('INSERT INTO lignes_facture (facture_id, produit_id, produit_nom, categorie, quantite, prix_unitaire, montant) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                            (facture_id, produit_id, produit['nom'], produit['categorie'], qte, produit['prix_vente_hall'], montant))
                conn.execute('UPDATE stocks SET quantite = quantite - %s WHERE produit_id = %s AND emplacement = %s', (qte, produit_id, 'Hall'))
                produits_ajoutes.append(f"{qte}x {produit['nom']}")
    
    if total_ajout > 0:
        conn.execute('UPDATE factures SET total_general = total_general + %s, reste_a_payer = reste_a_payer + %s WHERE id = %s', (total_ajout, total_ajout, facture_id))
        conn.commit()
        flash(f"✅ {', '.join(produits_ajoutes)} ajoutés pour {fmt(total_ajout)} FCFA", "success")
    else:
        flash("⚠️ Aucun produit sélectionné", "warning")
    conn.close()
    return redirect(url_for('factures'))

@app.route('/facture/<int:facture_id>/supprimer_ligne/<int:ligne_id>')
@check_access('acces_saisie')
def facture_supprimer_ligne(facture_id, ligne_id):
    """Supprimer une ligne de facture"""
    conn = get_db()
    facture = conn.execute('SELECT * FROM factures WHERE id = %s', (facture_id,)).fetchone()
    if not facture or facture['statut'] == 'soldée':
        flash("❌ Facture verrouillée", "danger"); conn.close()
        return redirect(url_for('factures'))
    
    ligne = conn.execute('SELECT * FROM lignes_facture WHERE id = %s AND facture_id = %s', (ligne_id, facture_id)).fetchone()
    if ligne:
        conn.execute('UPDATE stocks SET quantite = quantite + %s WHERE produit_id = %s AND emplacement = %s', (ligne['quantite'], ligne['produit_id'], 'Hall'))
        conn.execute('DELETE FROM lignes_facture WHERE id = %s', (ligne_id,))
        conn.execute('UPDATE factures SET total_general = total_general - %s, reste_a_payer = reste_a_payer - %s WHERE id = %s', (ligne['montant'], ligne['montant'], facture_id))
        conn.commit()
        flash(f"✅ {ligne['quantite']}x {ligne['produit_nom']} supprimé et stock remis", "success")
    conn.close()
    return redirect(url_for('factures'))

@app.route('/facture/<int:facture_id>/paiement', methods=['POST'])
@check_access('acces_saisie')
def facture_paiement(facture_id):
    """Enregistrer un paiement"""
    conn = get_db()
    facture = conn.execute('SELECT * FROM factures WHERE id = %s', (facture_id,)).fetchone()
    if not facture or facture['statut'] == 'soldée':
        flash("❌ Facture introuvable ou déjà soldée", "danger"); conn.close()
        return redirect(url_for('factures'))
    
    montant = float(request.form.get('montant', 0) or 0)
    mode = request.form.get('mode_paiement', 'especes')
    notes = request.form.get('notes', '').strip()
    
    if montant <= 0 or montant > facture['reste_a_payer']:
        flash(f"⚠️ Montant invalide (Max: {fmt(facture['reste_a_payer'])} FCFA)", "danger"); conn.close()
        return redirect(url_for('factures'))
    
    conn.execute('INSERT INTO paiements_facture (facture_id, montant, mode_paiement, utilisateur_id, notes) VALUES (%s, %s, %s, %s, %s)', (facture_id, montant, mode, session['user_id'], notes))
    nouveau_reste = facture['reste_a_payer'] - montant
    nouveau_total_paye = facture['total_paye'] + montant
    
    if nouveau_reste <= 0:
        conn.execute('UPDATE factures SET total_paye = %s, reste_a_payer = 0, statut = %s, date_fermeture = %s WHERE id = %s', (nouveau_total_paye, 'soldée', datetime.now(), facture_id))
        flash(f"✅ Facture {facture['numero']} soldée ! Total: {fmt(nouveau_total_paye)} FCFA", "success")
    else:
        conn.execute('UPDATE factures SET total_paye = %s, reste_a_payer = %s WHERE id = %s', (nouveau_total_paye, nouveau_reste, facture_id))
        flash(f"✅ Paiement de {fmt(montant)} FCFA enregistré. Reste: {fmt(nouveau_reste)} FCFA", "success")
    
    conn.commit(); conn.close()
    return redirect(url_for('factures'))

# ==========================================
# 📊 RÉCAPITULATIF DES VENTES (NOUVEAU)
# ==========================================

@app.route('/recapitulatif')
@check_access('acces_historique')
def recapitulatif():
    """Page de récapitulatif des ventes avec stock"""
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    date_debut = request.args.get('date_debut', today)
    date_fin = request.args.get('date_fin', today)
    
    # Récupérer les quantités vendues via la caisse classique (par type)
    ventes_classiques = conn.execute('''
        SELECT lv.produit_id,
               SUM(CASE WHEN lv.type_vente = %s THEN lv.quantite ELSE 0 END) as qte_hall,
               SUM(CASE WHEN lv.type_vente = %s THEN lv.quantite ELSE 0 END) as qte_bar,
               SUM(CASE WHEN lv.type_vente = %s THEN lv.quantite ELSE 0 END) as qte_kit
        FROM lignes_vente lv
        JOIN ventes v ON lv.vente_id = v.id
        WHERE date(v.date_heure) BETWEEN %s AND %s
        GROUP BY lv.produit_id
    ''', ('hall', 'bar', 'kit', date_debut, date_fin)).fetchall()
    ventes_classiques_dict = {row['produit_id']: row for row in ventes_classiques}
    
    # Récupérer les quantités vendues via les factures
    ventes_factures = conn.execute('''
        SELECT lf.produit_id, SUM(lf.quantite) as qte_commande
        FROM lignes_facture lf
        JOIN factures f ON lf.facture_id = f.id
        WHERE date(f.date_ouverture) BETWEEN %s AND %s
        GROUP BY lf.produit_id
    ''', (date_debut, date_fin)).fetchall()
    ventes_factures_dict = {row['produit_id']: row['qte_commande'] for row in ventes_factures}
    
    # Récupérer tous les produits avec leur stock actuel
    produits = conn.execute('''
        SELECT p.id, p.nom, p.categorie, COALESCE(s.quantite, 0) as stock_actuel
        FROM produits p
        LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s
        ORDER BY p.categorie, p.nom
    ''', ('Hall',)).fetchall()
    
    # Construire le tableau de récapitulatif
    recap_data = []
    total_general_hall = 0
    total_general_bar = 0
    total_general_kit = 0
    total_general_commande = 0
    total_general_vendu = 0
    
    for p in produits:
        pid = p['id']
        qte_hall = ventes_classiques_dict.get(pid, {}).get('qte_hall', 0) or 0
        qte_bar = ventes_classiques_dict.get(pid, {}).get('qte_bar', 0) or 0
        qte_kit = ventes_classiques_dict.get(pid, {}).get('qte_kit', 0) or 0
        qte_commande = ventes_factures_dict.get(pid, 0) or 0
        total_vendu = qte_hall + qte_bar + qte_kit + qte_commande
        reste_stock = p['stock_actuel'] - total_vendu
        
        # Ne montrer que les produits qui ont été vendus OU qui ont du stock
        if total_vendu > 0 or p['stock_actuel'] > 0:
            recap_data.append({
                'nom': p['nom'],
                'categorie': p['categorie'] or 'AUTRES',
                'stock_actuel': p['stock_actuel'],
                'qte_hall': qte_hall,
                'qte_bar': qte_bar,
                'qte_kit': qte_kit,
                'qte_commande': qte_commande,
                'total_vendu': total_vendu,
                'reste_stock': reste_stock
            })
            total_general_hall += qte_hall
            total_general_bar += qte_bar
            total_general_kit += qte_kit
            total_general_commande += qte_commande
            total_general_vendu += total_vendu
    
    # Totaux financiers de la période
    total_ventes_caisse = conn.execute('SELECT COALESCE(SUM(total), 0) as total FROM ventes WHERE date(date_heure) BETWEEN %s AND %s', (date_debut, date_fin)).fetchone()['total']
    total_ventes_factures = conn.execute("SELECT COALESCE(SUM(total_paye), 0) as total FROM factures WHERE statut = 'soldée' AND date(date_fermeture) BETWEEN %s AND %s", (date_debut, date_fin)).fetchone()['total']
    total_general = total_ventes_caisse + total_ventes_factures
    
    conn.close()
    return render_template('recapitulatif.html',
                          recap_data=recap_data,
                          date_debut=date_debut,
                          date_fin=date_fin,
                          total_ventes_caisse=fmt(total_ventes_caisse),
                          total_ventes_factures=fmt(total_ventes_factures),
                          total_general=fmt(total_general),
                          total_general_hall=total_general_hall,
                          total_general_bar=total_general_bar,
                          total_general_kit=total_general_kit,
                          total_general_commande=total_general_commande,
                          total_general_vendu=total_general_vendu,
                          date_jour=datetime.now().strftime('%d/%m/%Y'))

# ==========================================
# 2. PRODUITS
# ==========================================

@app.route('/produits')
@check_access('acces_produits')
def produits():
    conn = get_db()
    liste = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s ORDER BY p.categorie, p.nom', ('Hall',)).fetchall()
    conn.close()
    return render_template('produits.html', produits=liste)

@app.route('/telecharger_modele_produits')
@check_access('acces_produits')
def telecharger_modele_produits():
    df = pd.DataFrame({'Nom': ['Ex: HEINEKEN 33'], 'Categorie': ['AUTRES'], 'Prix Achat': [500], 'Prix Vente Hall': [700], 'Prix Kit': [2000], 'Prix Bar': [800], 'Stock': [100]})
    path = os.path.join(os.getcwd(), 'modele_import_produits.xlsx')
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

@app.route('/importer_produits', methods=['POST'])
@check_access('acces_produits')
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
            conn.execute('INSERT INTO produits (nom, categorie, prix_achat, prix_vente_hall, prix_kit, prix_bar, seuil_alerte) VALUES (%s, %s, %s, %s, %s, %s, 5) ON CONFLICT (nom) DO NOTHING', (nom, cat, pa, pv, pk, pb))
            pid = conn.execute('SELECT id FROM produits WHERE nom = %s', (nom,)).fetchone()[0]
            if st > 0: conn.execute('INSERT INTO stocks (produit_id, emplacement, quantite) VALUES (%s, %s, %s) ON CONFLICT (produit_id, emplacement) DO NOTHING', (pid, "Hall", st))
            count += 1
        conn.commit(); conn.close(); flash(f"✅ {count} produits importés.", "success")
    except Exception as e: flash(f"❌ Erreur: {e}", "danger")
    return redirect(url_for('produits'))

@app.route('/modifier_produit/<int:pid>', methods=['GET', 'POST'])
@check_access('acces_produits')
def modifier_produit(pid):
    conn = get_db()
    if request.method == 'POST':
        nom = request.form['nom'].strip()
        prix_hall = request.form['prix_hall']
        prix_kit = request.form.get('prix_kit', 0) or 0
        prix_bar = request.form.get('prix_bar', 0) or 0
        existe = conn.execute('SELECT id FROM produits WHERE nom = %s AND id != %s', (nom, pid)).fetchone()
        if existe: flash("⚠️ Ce nom existe déjà.", "warning"); conn.close(); return redirect(url_for('modifier_produit', pid=pid))
        conn.execute('UPDATE produits SET nom=%s, prix_vente_hall=%s, prix_kit=%s, prix_bar=%s WHERE id=%s', (nom, prix_hall, prix_kit, prix_bar, pid))
        conn.commit(); conn.close(); flash("✅ Produit modifié !", "success"); return redirect(url_for('produits'))
    p = conn.execute('SELECT * FROM produits WHERE id = %s', (pid,)).fetchone(); conn.close()
    return render_template('modifier_produit.html', produit=p)

@app.route('/supprimer_produit/<int:pid>')
@check_access('acces_produits')
def supprimer_produit(pid):
    conn = get_db()
    if conn.execute('SELECT COUNT(*) as c FROM lignes_vente WHERE produit_id = %s', (pid,)).fetchone()['c'] > 0: flash("⚠️ Produit déjà vendu.", "danger")
    else:
        conn.execute('DELETE FROM stocks WHERE produit_id = %s', (pid,)); conn.execute('DELETE FROM produits WHERE id = %s', (pid,)); conn.commit()
        flash("✅ Produit supprimé.", "success")
    conn.close(); return redirect(url_for('produits'))

# ==========================================
# 3. VENTES DU JOUR (CAISSE)
# ==========================================

@app.route('/caisse', methods=['GET', 'POST'])
@check_access('acces_saisie')
def caisse():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d'); date_saisie = request.args.get('date_saisie', today)
    if conn.execute('SELECT id FROM clotures_caisse WHERE date_cloture = %s', (date_saisie,)).fetchone():
        flash("⛔ La caisse de ce jour est déjà clôturée.", "danger"); conn.close(); return redirect(url_for('caisse'))
    
    if request.method == 'POST':
        dh = datetime.now().strftime('%Y-%m-%d %H:%M:%S'); total_vente = 0; lignes = []
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
                    for qte, prix, tipe in [(qte_hall, p['prix_vente_hall'], 'hall'), (qte_kit, p['prix_kit'] or p['prix_vente_hall'], 'kit'), (qte_bar, p['prix_bar'] or p['prix_vente_hall'], 'bar')]:
                        if qte > 0:
                            lignes.append({'pid': pid, 'qte': qte, 'prix': prix, 'mt': qte*prix, 'type': tipe})
                            conn.execute('UPDATE stocks SET quantite = quantite - %s WHERE produit_id = %s AND emplacement = %s', (qte, pid, 'Hall'))
        
        if total_vente == 0: flash("⚠️ Aucune vente.", "warning"); conn.close(); return redirect(url_for('caisse', date_saisie=date_saisie))
        pay_especes = float(request.form.get('montant_especes', 0) or 0)
        pay_wave = float(request.form.get('montant_wave', 0) or 0)
        pay_orange = float(request.form.get('montant_orange', 0) or 0)
        motif_ecart = request.form.get('motif_ecart', '').strip()
        total_paye = pay_especes + pay_wave + pay_orange
        ecart = total_paye - total_vente
        if abs(ecart) > 0:
            if not motif_ecart: flash("⚠️ Motif obligatoire en cas d'écart.", "danger"); conn.close(); return redirect(url_for('caisse', date_saisie=date_saisie))
            conn.execute('INSERT INTO ecarts_caisse (date_ecart, heure_ecart, montant_ecart, motif, utilisateur_id) VALUES (%s, %s, %s, %s, %s)', (date_saisie, datetime.now().strftime('%H:%M:%S'), ecart, motif_ecart, session['user_id']))
        modes_paiement = []
        if pay_especes > 0: modes_paiement.append(('especes', pay_especes))
        if pay_wave > 0: modes_paiement.append(('wave', pay_wave))
        if pay_orange > 0: modes_paiement.append(('orange_money', pay_orange))
        if not modes_paiement: modes_paiement.append(('especes', total_vente))
        premier_mode = True
        for mode, montant_mode in modes_paiement:
            cur = conn.execute('INSERT INTO ventes (date_heure, caissier_id, emplacement_vente, total, mode_paiement, client_id) VALUES (%s, 1, %s, %s, %s, NULL) RETURNING id', (dh, 'Hall', montant_mode, mode))
            vid = cur.fetchone()['id']
            if premier_mode:
                for l in lignes: conn.execute('INSERT INTO lignes_vente (vente_id, produit_id, quantite, prix_unitaire, montant_kit, type_vente) VALUES (%s, %s, %s, %s, %s, %s)', (vid, l['pid'], l['qte'], l['prix'], l['mt'], l['type']))
                premier_mode = False
        conn.commit(); conn.close(); flash(f"✅ Vente enregistrée ! Total: {fmt(total_vente)} FCFA", "success")
        return redirect(url_for('caisse', date_saisie=date_saisie))

    prods = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s ORDER BY nom', ('Hall',)).fetchall()
    tj = conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = %s', (date_saisie,)).fetchone()['v']
    conn.close()
    return render_template('caisse.html', produits=prods, total_jour=tj, date_jour=today, caisse_fermee=False, date_saisie=date_saisie)

# ==========================================
# 3.bis COMMANDES (CRÉDIT)
# ==========================================

@app.route('/commandes', methods=['GET', 'POST'])
@check_access('acces_commandes')
def commandes():
    conn = get_db()
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        if not client_id: flash("⚠️ Client obligatoire.", "danger"); conn.close(); return redirect(url_for('commandes'))
        client = conn.execute('SELECT nom FROM clients WHERE id = %s', (client_id,)).fetchone()
        nom_client = client['nom'].strip() if client else 'CLI'
        prefixe = nom_client[:3].upper().replace(' ', '').ljust(3, 'X')
        dh = datetime.now().strftime('%Y-%m-%d %H:%M:%S'); total_commande = 0; lignes = []
        for p in conn.execute('SELECT * FROM produits').fetchall():
            pid = p['id']
            qte = int(request.form.get(f'qte_cmd_{pid}', 0) or 0)
            prix = float(request.form.get(f'prix_cmd_{pid}', 0) or 0)
            if qte > 0 and prix > 0:
                montant = qte * prix; total_commande += montant
                lignes.append({'pid': pid, 'qte': qte, 'prix': prix, 'mt': montant})
                conn.execute('UPDATE stocks SET quantite = quantite - %s WHERE produit_id = %s AND emplacement = %s', (qte, pid, 'Hall'))
        if total_commande == 0: flash("⚠️ Aucune commande.", "warning"); conn.close(); return redirect(url_for('commandes'))
        dernier_numero = conn.execute('SELECT MAX(CAST(SUBSTR(numero_commande, 9) AS INTEGER)) as max_num FROM commandes WHERE numero_commande LIKE %s', (f'CMD-{prefixe}-%',)).fetchone()['max_num']
        nouveau_numero = f"CMD-{prefixe}-{(dernier_numero or 0) + 1:03d}"
        cur = conn.execute('INSERT INTO commandes (date_commande, client_id, total, statut, utilisateur_id, numero_commande) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id', (dh, client_id, total_commande, "Impayée", session['user_id'], nouveau_numero))
        cmd_id = cur.fetchone()['id']
        for l in lignes: conn.execute('INSERT INTO lignes_commande (commande_id, produit_id, quantite, prix_unitaire, montant) VALUES (%s, %s, %s, %s, %s)', (cmd_id, l['pid'], l['qte'], l['prix'], l['mt']))
        conn.execute('UPDATE clients SET solde_du = solde_du + %s WHERE id = %s', (total_commande, client_id))
        conn.commit(); conn.close(); enregistrer_action("Création de commande", "commandes", cmd_id, f"Commande {nouveau_numero}")
        flash(f"✅ Commande {nouveau_numero} enregistrée !", "success"); return redirect(url_for('commandes'))
    prods = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_hall FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s ORDER BY nom', ('Hall',)).fetchall()
    clients = conn.execute('SELECT * FROM clients ORDER BY nom').fetchall(); conn.close()
    return render_template('commandes.html', produits=prods, clients=clients)

# ==========================================
# 4. CLÔTURE DE CAISSE
# ==========================================

@app.route('/cloture', methods=['GET', 'POST'])
@check_access('acces_cloture')
def cloture():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    cloture_existante = conn.execute('SELECT * FROM clotures_caisse WHERE date_cloture = %s', (today,)).fetchone()
    if request.method == 'POST' and not cloture_existante:
        theo = conn.execute('SELECT mode_paiement, SUM(total) as total_montant FROM ventes WHERE date(date_heure) = %s AND mode_paiement != %s GROUP BY mode_paiement', (today, 'credit')).fetchall()
        theo_dict = {t['mode_paiement']: t['total_montant'] for t in theo}
        esp_theo, wave_theo, orange_theo = theo_dict.get('especes', 0), theo_dict.get('wave', 0), theo_dict.get('orange_money', 0)
        total_theo = esp_theo + wave_theo + orange_theo
        esp_reel = float(request.form.get('especes_reel', 0) or 0)
        wave_reel = float(request.form.get('wave_reel', 0) or 0)
        orange_reel = float(request.form.get('orange_reel', 0) or 0)
        total_reel = esp_reel + wave_reel + orange_reel
        conn.execute('INSERT INTO clotures_caisse (date_cloture, heure_cloture, utilisateur_id, especes_theoriques, especes_reelles, ecart_especes, wave_theoriques, wave_reelles, ecart_wave, orange_theoriques, orange_reelles, ecart_orange, total_theorique, total_reel, ecart_total, statut) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (today, datetime.now().strftime('%H:%M:%S'), session['user_id'], esp_theo, esp_reel, esp_reel - esp_theo, wave_theo, wave_reel, wave_reel - wave_theo, orange_theo, orange_reel, orange_reel - orange_theo, total_theo, total_reel, total_reel - total_theo, 'cloturee'))
        conn.commit(); conn.close(); flash("✅ Caisse clôturée !", "success"); return redirect(url_for('cloture'))
    data = {}
    if cloture_existante: data = dict(cloture_existante)
    else:
        theo = conn.execute('SELECT mode_paiement, SUM(total) as total_montant FROM ventes WHERE date(date_heure) = %s AND mode_paiement != %s GROUP BY mode_paiement', (today, 'credit')).fetchall()
        theo_dict = {t['mode_paiement']: t['total_montant'] for t in theo}
        data = {'especes_theoriques': theo_dict.get('especes', 0), 'wave_theoriques': theo_dict.get('wave', 0), 'orange_theoriques': theo_dict.get('orange_money', 0), 'total_theorique': sum(theo_dict.values()), 'heure_cloture': None}
    conn.close()
    return render_template('cloture.html', data=data, cloture_existante=cloture_existante, date_jour=today)

@app.route('/recu_cloture')
@check_access('acces_cloture')
def recu_cloture():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    c = conn.execute('SELECT * FROM clotures_caisse WHERE date_cloture = %s', (today,)).fetchone()
    u = conn.execute('SELECT nom FROM utilisateurs WHERE id = %s', (c['utilisateur_id'],)).fetchone() if c else None
    conn.close()
    if not c: return "Aucune clôture.", 404
    import base64
    logo_path = os.path.join(os.getcwd(), 'static', 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f: logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        logo_img = f'<img src="data:image/png;base64,{logo_base64}" style="max-width:250px; display:block; margin:0 auto 20px auto;">'
    else: logo_img = '<h2 style="text-align:center; color:#D4AF37;">🍾 CAVEPILOT</h2>'
    html = f"""<html><head><title>Reçu de Clôture - CavePilot</title>
    <style>
        body{{font-family:Arial;padding:20px;max-width:600px;margin:auto;background:#f9f9f9}}
        .container{{background:white;padding:30px;border-radius:10px;border-top:5px solid #D4AF37;box-shadow:0 5px 15px rgba(0,0,0,0.1)}}
        h2{{text-align:center;border-bottom:2px solid #D4AF37;padding-bottom:10px;color:#000}}
        table{{width:100%;border-collapse:collapse;margin-top:20px}}
        th,td{{border:1px solid #ddd;padding:10px;text-align:left}}
        th{{background-color:#D4AF37;color:#000;font-weight:bold}}
        .total{{font-weight:bold;background-color:#f0f0f0;color:#000}}
        .sign{{margin-top:50px;display:flex;justify-content:space-between}}
        .sign div{{border-top:1px solid #000;width:40%;text-align:center;padding-top:5px;font-weight:bold}}
        @media print{{.no-print{{display:none}}}}
    </style></head>
    <body>
        <div class="container">
            {logo_img}
            <h2>REÇU DE CLÔTURE DE CAISSE</h2>
            <p><strong>Date :</strong> {c['date_cloture']}<br>
            <strong>Caissier(ère) :</strong> {u['nom'] if u else 'Inconnu'}<br>
            <strong>Heure :</strong> {c['heure_cloture']}</p>
            <table>
                <tr><th>Mode</th><th>Théorique</th><th>Réel</th><th>Écart</th></tr>
                <tr><td>Espèces</td><td>{fmt(c['especes_theoriques'])}</td><td>{fmt(c['especes_reelles'])}</td><td>{fmt(c['ecart_especes'])}</td></tr>
                <tr><td>Wave</td><td>{fmt(c['wave_theoriques'])}</td><td>{fmt(c['wave_reelles'])}</td><td>{fmt(c['ecart_wave'])}</td></tr>
                <tr><td>Orange Money</td><td>{fmt(c['orange_theoriques'])}</td><td>{fmt(c['orange_reelles'])}</td><td>{fmt(c['ecart_orange'])}</td></tr>
                <tr class="total"><td>TOTAL</td><td>{fmt(c['total_theorique'])}</td><td>{fmt(c['total_reel'])}</td><td>{fmt(c['ecart_total'])}</td></tr>
            </table>
            <div class="sign">
                <div>Signature Caissier(ère)</div>
                <div>Signature Responsable</div>
            </div>
            <div class="no-print" style="text-align:center;margin-top:30px">
                <button onclick="window.print()" style="padding:10px 20px;font-size:16px;cursor:pointer;background:#D4AF37;color:#000;border:none;border-radius:5px;font-weight:bold;">🖨️ Imprimer / PDF</button>
            </div>
        </div>
    </body></html>"""
    return html

# ==========================================
# 5. APPROVISIONNEMENT
# ==========================================

@app.route('/approvisionnement', methods=['GET', 'POST'])
@check_access('acces_appro')
def approvisionnement():
    conn = get_db()
    if request.method == 'POST':
        produit_id = int(request.form['produit_id'])
        casiers = int(request.form['casiers']); btles_casier = int(request.form['bouteilles_par_casier'])
        prix_casier = float(request.form['prix_achat_casier']); emplacement = request.form['emplacement']
        total_btles = casiers * btles_casier; cout_unitaire = prix_casier / btles_casier if btles_casier > 0 else 0
        prod = conn.execute('SELECT * FROM produits WHERE id = %s', (produit_id,)).fetchone()
        marge_totale = (prod['prix_vente_hall'] - cout_unitaire) * total_btles
        conn.execute('INSERT INTO approvisionnements (date_appro, produit_id, casiers, bouteilles_par_casier, total_bouteilles, prix_achat_casier, cout_unitaire, prix_vente_actuel, marge_unitaire, marge_totale, emplacement) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)', (request.form['date_appro'], produit_id, casiers, btles_casier, total_btles, prix_casier, cout_unitaire, prod['prix_vente_hall'], prod['prix_vente_hall'] - cout_unitaire, marge_totale, emplacement))
        conn.execute('INSERT INTO stocks (produit_id, emplacement, quantite) VALUES (%s, %s, %s) ON CONFLICT(produit_id, emplacement) DO UPDATE SET quantite = quantite + %s', (produit_id, emplacement, total_btles, total_btles))
        conn.execute('UPDATE produits SET prix_achat = %s WHERE id = %s', (cout_unitaire, produit_id))
        conn.commit(); conn.close(); flash("✅ Approvisionnement enregistré !", "success"); return redirect(url_for('approvisionnement'))
    date_debut = request.args.get('date_debut', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    date_fin = request.args.get('date_fin', datetime.now().strftime('%Y-%m-%d'))
    appros = conn.execute('SELECT a.*, p.nom as produit_nom, p.categorie FROM approvisionnements a JOIN produits p ON a.produit_id = p.id WHERE a.date_appro BETWEEN %s AND %s ORDER BY a.date_appro DESC', (date_debut, date_fin)).fetchall()
    kpis = conn.execute('SELECT SUM(a.prix_achat_casier * a.casiers) as total_investi, SUM(a.marge_totale) as marge_brute, SUM(a.total_bouteilles) as total_bouteilles FROM approvisionnements a WHERE a.date_appro BETWEEN %s AND %s', (date_debut, date_fin)).fetchone()
    produits = conn.execute('SELECT * FROM produits ORDER BY categorie, nom').fetchall(); conn.close()
    return render_template('approvisionnement.html', appros=appros, produits=produits, kpis=kpis, date_debut=date_debut, date_fin=date_fin)

# ==========================================
# 6. HISTORIQUE
# ==========================================

@app.route('/historique')
@check_access('acces_historique')
def historique():
    conn = get_db()
    db = request.args.get('date_debut', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    df = request.args.get('date_fin', datetime.now().strftime('%Y-%m-%d'))
    cat_filtre = request.args.get('categorie', '')
    q = '''SELECT date(v.date_heure) as date_vente, p.nom as produit_nom, p.categorie,
                  SUM(CASE WHEN lv.type_vente = %s THEN lv.quantite ELSE 0 END) as qte_hall,
                  SUM(CASE WHEN lv.type_vente = %s THEN lv.quantite ELSE 0 END) as qte_kit,
                  SUM(CASE WHEN lv.type_vente = %s THEN lv.quantite ELSE 0 END) as qte_bar,
                  SUM(lv.montant_kit) as total_ligne
           FROM lignes_vente lv JOIN ventes v ON lv.vente_id = v.id JOIN produits p ON lv.produit_id = p.id
           WHERE date(v.date_heure) BETWEEN %s AND %s'''
    p = ['hall', 'kit', 'bar', db, df]
    if cat_filtre: q += ' AND p.categorie = %s'; p.append(cat_filtre)
    q += ' GROUP BY date(v.date_heure), p.id ORDER BY date_vente DESC, p.categorie, p.nom'
    lignes = conn.execute(q, p).fetchall()
    total_global = conn.execute('SELECT COALESCE(SUM(total), 0) as total FROM ventes WHERE date(date_heure) BETWEEN %s AND %s', [db, df]).fetchone()['total']
    categories = conn.execute('SELECT DISTINCT categorie FROM produits WHERE categorie IS NOT NULL ORDER BY categorie').fetchall()
    conn.close()
    return render_template('historique.html', lignes=lignes, date_debut=db, date_fin=df, categorie_filtre=cat_filtre, total_global=total_global, nb_lignes=len(lignes), categories=categories)

# ==========================================
# 7. CLIENTS & REMBOURSEMENTS
# ==========================================

@app.route('/clients', methods=['GET', 'POST'])
@check_access('acces_clients')
def clients():
    conn = get_db()
    if request.method == 'POST' and 'client_id' not in request.form:
        conn.execute('INSERT INTO clients (nom, telephone, adresse, solde_du, plafond_credit) VALUES (%s, %s, %s, 0, %s)', (request.form['nom'], request.form['telephone'], request.form.get('adresse', ''), float(request.form['plafond'] or 0)))
        conn.commit(); conn.close(); flash("✅ Client créé !", "success"); return redirect(url_for('clients'))
    lc = conn.execute('SELECT * FROM clients ORDER BY nom').fetchall()
    clients_with_data = []
    for c in lc:
        total_remb = conn.execute('SELECT COALESCE(SUM(montant), 0) as total FROM remboursements WHERE client_id = %s', (c['id'],)).fetchone()['total']
        solde = float(c['solde_du'] or 0); total_vendu = solde + total_remb
        taux = round((total_remb / total_vendu) * 100, 1) if total_vendu > 0 else 0
        c_dict = dict(c); c_dict['total_vendu_credit'] = total_vendu; c_dict['total_remboursements'] = total_remb; c_dict['taux_recouvrement'] = taux
        c_dict['commandes_impayees'] = [{'id': cmd['id'], 'numero': cmd['numero_commande'] or f"CMD-{c['nom'][:3].upper()}-001", 'date': cmd['date_commande'].strftime('%Y-%m-%d') if cmd['date_commande'] else '', 'total': float(cmd['total'])} for cmd in conn.execute('SELECT id, numero_commande, date_commande, total, statut FROM commandes WHERE client_id = %s AND statut = %s ORDER BY date_commande DESC', (c['id'], 'Impayée')).fetchall()]
        clients_with_data.append(c_dict)
    conn.close()
    return render_template('clients.html', clients=clients_with_data)

@app.route('/rembourser_client', methods=['POST'])
@check_access('acces_clients')
def rembourser_client():
    conn = get_db()
    client_id = request.form.get('client_id'); commande_id = request.form.get('commande_id'); montant = float(request.form.get('montant', 0) or 0); mode = request.form.get('mode_paiement', 'especes')
    if montant > 0 and client_id:
        client = conn.execute('SELECT solde_du FROM clients WHERE id = %s', (client_id,)).fetchone()
        if client and montant > client['solde_du']: flash(f"⚠️ Montant supérieur à la dette.", "danger")
        else:
            conn.execute('UPDATE clients SET solde_du = solde_du - %s WHERE id = %s', (montant, client_id))
            conn.execute('INSERT INTO remboursements (date_remboursement, client_id, commande_id, montant, mode_paiement, utilisateur_id) VALUES (%s, %s, %s, %s, %s, %s)', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), client_id, commande_id if commande_id else None, montant, mode, session['user_id']))
            if commande_id and abs(conn.execute('SELECT total FROM commandes WHERE id = %s', (commande_id,)).fetchone()['total'] - montant) < 1: conn.execute('UPDATE commandes SET statut = %s WHERE id = %s', ('Payée', commande_id))
            conn.commit(); flash(f"✅ Paiement de {fmt(montant)} FCFA enregistré !", "success")
    conn.close(); return redirect(url_for('clients'))

# ==========================================
# 8. PAIEMENTS
# ==========================================

@app.route('/paiements', methods=['GET'])
@check_access('acces_paiements')
def paiements():
    conn = get_db()
    db = request.args.get('date_debut', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    df = request.args.get('date_fin', datetime.now().strftime('%Y-%m-%d'))
    hist = conn.execute('SELECT r.*, c.nom as client_nom, co.numero_commande, u.nom as utilisateur_nom FROM remboursements r LEFT JOIN clients c ON r.client_id = c.id LEFT JOIN commandes co ON r.commande_id = co.id LEFT JOIN utilisateurs u ON r.utilisateur_id = u.id WHERE date(r.date_remboursement) BETWEEN %s AND %s ORDER BY r.date_remboursement DESC', (db, df)).fetchall()
    total_rembourse = conn.execute('SELECT COALESCE(SUM(montant), 0) as total FROM remboursements WHERE date(date_remboursement) BETWEEN %s AND %s', (db, df)).fetchone()['total']
    conn.close()
    return render_template('paiements.html', historique=hist, date_debut=db, date_fin=df, total_rembourse=total_rembourse, nb_paiements=len(hist))

# ==========================================
# 9. INVENTAIRE
# ==========================================

@app.route('/inventaire', methods=['GET', 'POST'])
@check_access('acces_inventaire')
def inventaire():
    conn = get_db()
    if request.method == 'POST':
        emp, di, note = request.form['emplacement'], request.form['date_inventaire'], request.form.get('note', '')
        cur = conn.execute('INSERT INTO inventaires (date_inventaire, emplacement, note, utilisateur_id) VALUES (%s, %s, %s, %s) RETURNING id', (di, emp, note, session['user_id']))
        iid = cur.fetchone()['id']; te = 0
        for k, v in request.form.items():
            if k.startswith('stock_physique_') and v:
                pid, sp = int(k.replace('stock_physique_', '')), int(v)
                st = conn.execute('SELECT COALESCE(quantite, 0) FROM stocks WHERE produit_id = %s AND emplacement = %s', (pid, emp)).fetchone()[0]
                ec = sp - st; te += ec
                conn.execute('INSERT INTO lignes_inventaire (inventaire_id, produit_id, stock_theorique, stock_physique, ecart) VALUES (%s, %s, %s, %s, %s)', (iid, pid, st, sp, ec))
                conn.execute('UPDATE stocks SET quantite = %s WHERE produit_id = %s AND emplacement = %s', (sp, pid, emp))
        conn.commit(); conn.close(); flash(f"{'⚠️' if te != 0 else '✅'} Inventaire validé ! Écart: {te}", "warning" if te!=0 else "success"); return redirect(url_for('inventaire'))
    emp = request.args.get('emplacement', 'Hall')
    prods = conn.execute('SELECT p.*, COALESCE(s.quantite, 0) as stock_theorique FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s ORDER BY p.categorie, p.nom', (emp,)).fetchall()
    hist = conn.execute('''
        SELECT i.id, i.date_inventaire, i.emplacement, i.note, i.utilisateur_id,
               u.nom as utilisateur_nom, COUNT(li.id) as nb_lignes, COALESCE(SUM(li.ecart), 0) as total_ecart
        FROM inventaires i
        LEFT JOIN utilisateurs u ON i.utilisateur_id = u.id
        LEFT JOIN lignes_inventaire li ON i.id = li.inventaire_id
        GROUP BY i.id, i.date_inventaire, i.emplacement, i.note, i.utilisateur_id, u.nom
        ORDER BY i.date_inventaire DESC
    ''').fetchall()
    conn.close()
    return render_template('inventaire.html', produits=prods, emplacement=emp, historique=hist, date_jour=datetime.now().strftime('%Y-%m-%d'))

@app.route('/export_inventaire/<fmt>')
@check_access('acces_inventaire')
def export_inventaire(fmt):
    emp = request.args.get('emplacement', 'Hall')
    di = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db()
    prods = conn.execute('SELECT p.nom, p.categorie, COALESCE(s.quantite, 0) as stock_theorique FROM produits p LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = %s ORDER BY p.categorie, p.nom', (emp,)).fetchall()
    conn.close()
    if fmt == 'excel':
        df = pd.DataFrame([{'Produit': p['nom'], 'Catégorie': p['categorie'], 'Stock Théorique': p['stock_theorique'], 'Stock Physique': '', 'Écart': '', 'Observation': ''} for p in prods])
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False, sheet_name='Inventaire')
        out.seek(0)
        return send_file(out, as_attachment=True, download_name=f'inventaire_{emp}_{di}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    elif fmt == 'csv':
        out = io.StringIO("Produit;Catégorie;Stock Théorique;Stock Physique;Écart;Observation\n")
        for p in prods: out.write(f"{p['nom']};{p['categorie']};{p['stock_theorique']};;;\n")
        r = make_response(out.getvalue())
        r.headers['Content-Type'] = 'text/csv; charset=utf-8'
        r.headers['Content-Disposition'] = f'attachment; filename=inventaire_{emp}_{di}.csv'
        return r
    return "Format non supporté", 400

# ==========================================
# 🔐 JOURNAL DE SÉCURITÉ & BACKUP
# ==========================================

@app.route('/journal_securite')
@check_access('acces_comptes')
def journal_securite():
    conn = get_db()
    connexions = conn.execute('SELECT * FROM journal_connexions ORDER BY date_connexion DESC LIMIT 50').fetchall()
    actions = conn.execute('SELECT * FROM journal_actions ORDER BY date_action DESC LIMIT 50').fetchall()
    tentatives = conn.execute('SELECT * FROM tentatives_connexion WHERE succes = 0 ORDER BY date_tentative DESC LIMIT 20').fetchall()
    conn.close()
    return render_template('journal_securite.html', connexions=connexions, actions=actions, tentatives=tentatives)

@app.route('/backup_db')
@check_access('acces_comptes')
def backup_db():
    flash("ℹ️ Avec Neon, les sauvegardes sont gérées automatiquement par la plateforme !", "info")
    return redirect(url_for('journal_securite'))

# ==========================================
# 🚀 LANCEMENT
# ==========================================

if __name__ == '__main__':
    print("🚀 Démarrage de CavePilot...")
    app.run(debug=True, host='127.0.0.1', port=5000)