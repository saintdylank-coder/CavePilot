from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'cle_secrete_cave_2026_professionnel'

def get_db():
    conn = sqlite3.connect('cave.db')
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================
# 1. TABLEAU DE BORD
# ==========================================
@app.route('/')
def dashboard():
    try:
        conn = get_db()
        total_produits = conn.execute('SELECT COUNT(*) as c FROM produits').fetchone()['c']
        stock_hall = conn.execute('SELECT COALESCE(SUM(quantite), 0) as s FROM stocks WHERE emplacement="Hall"').fetchone()['s']
        valeur_stock = conn.execute('SELECT COALESCE(SUM(s.quantite * p.prix_vente_hall), 0) as v FROM stocks s JOIN produits p ON s.produit_id = p.id WHERE s.emplacement="Hall"').fetchone()['v']
        total_credits = conn.execute('SELECT COALESCE(SUM(solde_du), 0) as c FROM clients').fetchone()['c']
        total_clients = conn.execute('SELECT COUNT(*) as c FROM clients').fetchone()['c']
        
        today = datetime.now().strftime('%Y-%m-%d')
        ventes_jour = conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = ?', (today,)).fetchone()['v']
        
        conn.close()
        
        valeur_stock_fmt = f"{valeur_stock:,.0f}".replace(',', ' ')
        total_credits_fmt = f"{total_credits:,.0f}".replace(',', ' ')
        ventes_jour_fmt = f"{ventes_jour:,.0f}".replace(',', ' ')
        
        return render_template('dashboard.html', 
                               total_produits=total_produits, 
                               stock_hall=stock_hall, 
                               valeur_stock=valeur_stock_fmt,
                               total_credits=total_credits_fmt,
                               total_clients=total_clients,
                               ventes_jour=ventes_jour_fmt,
                               date_jour=datetime.now().strftime('%d/%m/%Y'))
    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "danger")
        return render_template('dashboard.html', 
                               total_produits=0, stock_hall=0, valeur_stock="0",
                               total_credits="0", total_clients=0, ventes_jour="0",
                               date_jour=datetime.now().strftime('%d/%m/%Y'))

# ==========================================
# 2. PAGE PRODUITS
# ==========================================
@app.route('/produits')
def produits():
    try:
        conn = get_db()
        liste = conn.execute('''
            SELECT p.*, COALESCE(s.quantite, 0) as stock_hall 
            FROM produits p 
            LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = 'Hall'
            ORDER BY p.categorie, p.nom
        ''').fetchall()
        conn.close()
        return render_template('produits.html', produits=liste)
    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "danger")
        return redirect(url_for('dashboard'))

# ==========================================
# 3. MODIFIER LES PRIX
# ==========================================
@app.route('/modifier_prix/<int:produit_id>', methods=['GET', 'POST'])
def modifier_prix(produit_id):
    try:
        conn = get_db()
        
        if request.method == 'POST':
            prix_hall = float(request.form['prix_hall'])
            prix_kit = float(request.form['prix_kit']) if request.form['prix_kit'] else 0
            prix_bar = float(request.form['prix_bar']) if request.form['prix_bar'] else 0
            
            conn.execute('UPDATE produits SET prix_vente_hall=?, prix_kit=?, prix_bar=? WHERE id=?', 
                         (prix_hall, prix_kit, prix_bar, produit_id))
            conn.commit()
            conn.close()
            flash("✅ Prix modifiés avec succès !", "success")
            return redirect(url_for('produits'))
            
        produit = conn.execute('SELECT * FROM produits WHERE id = ?', (produit_id,)).fetchone()
        conn.close()
        return render_template('modifier_prix.html', produit=produit)
    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "danger")
        return redirect(url_for('produits'))

# ==========================================
# 4. CAISSE / VENTE (CORRIGÉ)
# ==========================================
@app.route('/caisse', methods=['GET', 'POST'])
def caisse():
    try:
        conn = get_db()
        
        if request.method == 'POST':
            client_id = request.form.get('client_id')
            mode_paiement = request.form.get('mode_paiement', 'especes')
            date_heure = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            total_vente = 0
            total_commande = 0
            lignes_vente = []
            erreurs = []
            
            # Parcourir tous les produits pour trouver les quantités saisies
            for key, value in request.form.items():
                if key.startswith('qte_hall_') or key.startswith('qte_kit_') or key.startswith('qte_bar_') or key.startswith('qte_commande_'):
                    produit_id = int(key.split('_')[-1])
                    quantite = int(value) if value else 0
                    
                    if quantite > 0:
                        produit = conn.execute('SELECT * FROM produits WHERE id = ?', (produit_id,)).fetchone()
                        stock_actuel = conn.execute('SELECT quantite FROM stocks WHERE produit_id = ? AND emplacement = "Hall"', (produit_id,)).fetchone()
                        stock_dispo = stock_actuel['quantite'] if stock_actuel else 0
                        
                        # Vérifier le stock
                        if quantite > stock_dispo and not key.startswith('qte_commande_'):
                            erreurs.append(f"Stock insuffisant pour {produit['nom']} (disponible: {stock_dispo})")
                            continue
                        
                        if key.startswith('qte_hall_'):
                            prix = produit['prix_vente_hall']
                            type_vente = 'Hall'
                        elif key.startswith('qte_kit_'):
                            prix = produit['prix_kit'] if produit['prix_kit'] else produit['prix_vente_hall']
                            type_vente = 'Kit'
                        elif key.startswith('qte_bar_'):
                            prix = produit['prix_bar'] if produit['prix_bar'] else produit['prix_vente_hall']
                            type_vente = 'Bar'
                        else:  # qte_commande_
                            prix = produit['prix_vente_hall']
                            type_vente = 'Commande'
                            total_commande += quantite * prix
                        
                        montant_ligne = quantite * prix
                        if not key.startswith('qte_commande_'):
                            total_vente += montant_ligne
                        
                        lignes_vente.append({
                            'produit_id': produit_id,
                            'quantite': quantite,
                            'prix_unitaire': prix,
                            'montant': montant_ligne,
                            'type_vente': type_vente
                        })
            
            # S'il y a des erreurs, on arrête
            if erreurs:
                for err in erreurs:
                    flash(f"⚠️ {err}", "warning")
                conn.close()
                return redirect(url_for('caisse'))
            
            # Diminuer le stock pour toutes les ventes (y compris commandes)
            for ligne in lignes_vente:
                conn.execute('''
                    UPDATE stocks SET quantite = quantite - ? 
                    WHERE produit_id = ? AND emplacement = 'Hall'
                ''', (ligne['quantite'], ligne['produit_id']))
            
            # Si c'est une commande (crédit), mettre à jour le solde du client
            if client_id and total_commande > 0:
                conn.execute('UPDATE clients SET solde_du = solde_du + ? WHERE id = ?', 
                            (total_commande, client_id))
            
            # Enregistrer la vente
            cursor = conn.execute('''
                INSERT INTO ventes (date_heure, caissier_id, emplacement_vente, total, mode_paiement, client_id)
                VALUES (?, 1, 'Hall', ?, ?, ?)
            ''', (date_heure, total_vente + total_commande, mode_paiement, client_id if total_commande > 0 else None))
            
            vente_id = cursor.lastrowid
            
            # Enregistrer les lignes de vente
            for ligne in lignes_vente:
                conn.execute('''
                    INSERT INTO lignes_vente (vente_id, produit_id, quantite, prix_unitaire, montant_kit)
                    VALUES (?, ?, ?, ?, ?)
                ''', (vente_id, ligne['produit_id'], ligne['quantite'], ligne['prix_unitaire'], ligne['montant']))
            
            conn.commit()
            conn.close()
            
            total_final = total_vente + total_commande
            flash(f"✅ Vente enregistrée ! Total : {total_final:,.0f} FCFA", "success")
            return redirect(url_for('caisse'))

        produits = conn.execute('''
            SELECT p.*, COALESCE(s.quantite, 0) as stock_hall 
            FROM produits p 
            LEFT JOIN stocks s ON p.id = s.produit_id AND s.emplacement = 'Hall'
            ORDER BY p.categorie, p.nom
        ''').fetchall()
        clients = conn.execute('SELECT * FROM clients ORDER BY nom').fetchall()
        
        today = datetime.now().strftime('%Y-%m-%d')
        total_jour = conn.execute('SELECT COALESCE(SUM(total), 0) as v FROM ventes WHERE date(date_heure) = ?', (today,)).fetchone()['v']
        
        conn.close()
        return render_template('caisse.html', produits=produits, clients=clients, total_jour=total_jour)
    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "danger")
        return redirect(url_for('dashboard'))

# ==========================================
# 5. GESTION DES CLIENTS
# ==========================================
@app.route('/clients', methods=['GET', 'POST'])
def clients():
    try:
        conn = get_db()
        
        if request.method == 'POST':
            nom = request.form['nom']
            telephone = request.form['telephone']
            plafond = float(request.form['plafond'] if request.form['plafond'] else 0)
            
            conn.execute('INSERT INTO clients (nom, telephone, solde_du, plafond_credit) VALUES (?, ?, 0, ?)',
                        (nom, telephone, plafond))
            conn.commit()
            conn.close()
            flash("✅ Client créé avec succès !", "success")
            return redirect(url_for('clients'))
        
        liste_clients = conn.execute('SELECT * FROM clients ORDER BY nom').fetchall()
        conn.close()
        return render_template('clients.html', clients=liste_clients)
    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "danger")
        return redirect(url_for('dashboard'))

# ==========================================
# 6. PAIEMENTS
# ==========================================
@app.route('/paiements', methods=['GET', 'POST'])
def paiements():
    try:
        conn = get_db()
        
        if request.method == 'POST':
            date_paiement = request.form.get('date_paiement', datetime.now().strftime('%Y-%m-%d'))
            montant_especes = float(request.form.get('montant_especes', 0))
            montant_wave = float(request.form.get('montant_wave', 0))
            montant_orange = float(request.form.get('montant_orange', 0))
            
            if montant_especes > 0:
                conn.execute('INSERT INTO paiements (date_paiement, mode_paiement, montant) VALUES (?, "especes", ?)', 
                            (date_paiement, montant_especes))
            
            if montant_wave > 0:
                conn.execute('INSERT INTO paiements (date_paiement, mode_paiement, montant) VALUES (?, "wave", ?)', 
                            (date_paiement, montant_wave))
            
            if montant_orange > 0:
                conn.execute('INSERT INTO paiements (date_paiement, mode_paiement, montant) VALUES (?, "orange_money", ?)', 
                            (date_paiement, montant_orange))
            
            conn.commit()
            conn.close()
            flash("✅ Paiements enregistrés avec succès !", "success")
            return redirect(url_for('paiements'))
        
        today = datetime.now().strftime('%Y-%m-%d')
        stats = conn.execute('''
            SELECT mode_paiement, COUNT(*) as nombre, SUM(montant) as total_montant
            FROM paiements
            WHERE date(date_paiement) = ?
            GROUP BY mode_paiement
        ''', (today,)).fetchall()
        
        paiements_jour = conn.execute('''
            SELECT * FROM paiements
            WHERE date(date_paiement) = ?
            ORDER BY date_paiement DESC
        ''', (today,)).fetchall()
        
        conn.close()
        return render_template('paiements.html', stats=stats, paiements=paiements_jour)
    except Exception as e:
        flash(f"❌ Erreur : {str(e)}", "danger")
        return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)