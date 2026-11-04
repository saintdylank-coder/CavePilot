import sqlite3
import hashlib
from datetime import datetime, timedelta
import random

# Connexion à la base avec row_factory pour utiliser les noms de colonnes
conn = sqlite3.connect('cave.db')
conn.row_factory = sqlite3.Row  # ✅ C'est la ligne qui manquait !
curseur = conn.cursor()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

print("🚀 Génération des données de test...")

# ==========================================
# 1. VÉRIFIER QUE LES PRODUITS EXISTENT
# ==========================================
nb_produits = curseur.execute('SELECT COUNT(*) FROM produits').fetchone()[0]

if nb_produits == 0:
    print("⚠️ Aucun produit trouvé. Ajout de produits de base...")
    produits_test = [
        ('HEINEKEN 33', 'AUTRES', 500, 700, 2000, 800),
        ('CASTEL 33', 'AUTRES', 400, 600, 1800, 700),
        ('CASTEL 50', 'AUTRES', 500, 700, 2200, 800),
        ('BOCK 50', 'AUTRES', 450, 650, 2000, 750),
        ('BOCK 66', 'AUTRES', 500, 700, 2200, 800),
        ('BUDWEISER', 'AUTRES', 600, 900, 2500, 1000),
        ('CORONA EXTRA', 'AUTRES', 700, 1000, 3000, 1200),
        ('DESPERADOS', 'AUTRES', 600, 900, 2800, 1000),
        ('CHAMPAGNE MOËT', 'CHAMPAGNES', 15000, 25000, 0, 0),
        ('VIN ROUGE BORDEAUX', 'VINS', 3000, 5000, 0, 0),
        ('VIN BLANC CHARDONNAY', 'VINS', 3500, 5500, 0, 0),
        ('WHISKY JOHNNIE WALKER', 'CHAMPAGNES', 20000, 35000, 0, 0),
        ('COGNAC HENNESSY', 'CHAMPAGNES', 25000, 45000, 0, 0),
        ('RICARD 51', 'CHAMPAGNES', 8000, 12000, 0, 0),
        ('VODKA ABSOLUT', 'CHAMPAGNES', 12000, 20000, 0, 0),
    ]
    
    for nom, cat, pa, pv, pk, pb in produits_test:
        curseur.execute('''
            INSERT OR IGNORE INTO produits (nom, categorie, prix_achat, prix_vente_hall, prix_kit, prix_bar, seuil_alerte)
            VALUES (?, ?, ?, ?, ?, ?, 5)
        ''', (nom, cat, pa, pv, pk, pb))
        
        cursor2 = curseur.execute('SELECT id FROM produits WHERE nom = ?', (nom,))
        prod_id = cursor2.fetchone()[0]
        stock = random.randint(20, 100)
        curseur.execute('INSERT OR IGNORE INTO stocks (produit_id, emplacement, quantite) VALUES (?, "Hall", ?)', (prod_id, stock))
    
    conn.commit()
    print(f"✅ {len(produits_test)} produits ajoutés")
else:
    print(f"✅ {nb_produits} produits déjà présents")

# ==========================================
# 2. CRÉER DES CLIENTS FICTIFS
# ==========================================
nb_clients = curseur.execute('SELECT COUNT(*) FROM clients').fetchone()[0]

if nb_clients == 0:
    print("👥 Création de clients fictifs...")
    clients_test = [
        ('Jean Kouadio', '0707010203', 'Cocody Angré', 100000),
        ('Marie Bah', '0505040506', 'Yopougon Siporex', 150000),
        ('Ibrahim Traoré', '0101070809', 'Abobo Baoulé', 80000),
        ('Aminata Koné', '0707101112', 'Plateau Centre', 200000),
        ('Moussa Diabaté', '0505131415', 'Treichon Zone 4', 120000),
    ]
    
    for nom, tel, adresse, plafond in clients_test:
        curseur.execute('''
            INSERT INTO clients (nom, telephone, adresse, solde_du, plafond_credit)
            VALUES (?, ?, ?, 0, ?)
        ''', (nom, tel, adresse, plafond))
    
    conn.commit()
    print(f"✅ {len(clients_test)} clients créés")
else:
    print(f"✅ {nb_clients} clients déjà présents")

# ==========================================
# 3. GÉNÉRER DES VENTES SUR 7 JOURS
# ==========================================
print("💰 Génération des ventes sur 7 jours...")

produits = curseur.execute('SELECT * FROM produits').fetchall()
clients = curseur.execute('SELECT * FROM clients').fetchall()
modes_paiement = ['especes', 'wave', 'orange_money']

total_ventes_generees = 0

for jour in range(6, -1, -1):
    date_vente = (datetime.now() - timedelta(days=jour)).strftime('%Y-%m-%d')
    nb_ventes_jour = random.randint(3, 8)  # 3 à 8 ventes par jour
    
    for _ in range(nb_ventes_jour):
        heure = f"{random.randint(8, 20):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
        date_heure = f"{date_vente} {heure}"
        
        # Choisir un mode de paiement
        mode = random.choice(modes_paiement)
        
        # 30% de chances que ce soit un crédit
        is_credit = random.random() < 0.3
        client_id = None
        if is_credit and clients:
            client = random.choice(clients)
            client_id = client['id']  # ✅ Maintenant ça marche grâce à row_factory
            mode = 'credit'
        
        # Créer 1 à 3 lignes de vente
        nb_lignes = random.randint(1, 3)
        total_vente = 0
        lignes_data = []
        
        for _ in range(nb_lignes):
            produit = random.choice(produits)
            quantite = random.randint(1, 5)
            
            # Choisir le type de vente
            type_vente = random.choice(['hall', 'hall', 'hall', 'kit', 'bar'])
            if type_vente == 'hall':
                prix = produit['prix_vente_hall']
            elif type_vente == 'kit':
                prix = produit['prix_kit'] if produit['prix_kit'] else produit['prix_vente_hall']
            else:
                prix = produit['prix_bar'] if produit['prix_bar'] else produit['prix_vente_hall']
            
            montant = quantite * prix
            total_vente += montant
            lignes_data.append((produit['id'], quantite, prix, montant))
        
        # Insérer la vente
        curseur.execute('''
            INSERT INTO ventes (date_heure, caissier_id, emplacement_vente, total, mode_paiement, client_id)
            VALUES (?, 1, "Hall", ?, ?, ?)
        ''', (date_heure, total_vente, mode, client_id))
        
        vente_id = curseur.lastrowid
        
        # Insérer les lignes
        for prod_id, qte, prix, montant in lignes_data:
            curseur.execute('''
                INSERT INTO lignes_vente (vente_id, produit_id, quantite, prix_unitaire, montant_kit)
                VALUES (?, ?, ?, ?, ?)
            ''', (vente_id, prod_id, qte, prix, montant))
        
        # Si crédit, mettre à jour le solde du client
        if client_id:
            curseur.execute('UPDATE clients SET solde_du = solde_du + ? WHERE id = ?', (total_vente, client_id))
        
        total_ventes_generees += 1

conn.commit()
print(f"✅ {total_ventes_generees} ventes générées sur 7 jours")

# ==========================================
# 4. GÉNÉRER DES PAIEMENTS
# ==========================================
print("💳 Génération des paiements...")

for jour in range(6, -1, -1):
    date_paiement = (datetime.now() - timedelta(days=jour)).strftime('%Y-%m-%d')
    
    for mode in modes_paiement:
        montant = random.randint(5000, 50000)
        curseur.execute('''
            INSERT INTO paiements (date_paiement, mode_paiement, montant)
            VALUES (?, ?, ?)
        ''', (date_paiement, mode, montant))

conn.commit()
print("✅ Paiements générés")

# ==========================================
# RÉSUMÉ
# ==========================================
print("\n" + "="*50)
print("🎉 DONNÉES DE TEST GÉNÉRÉES AVEC SUCCÈS !")
print("="*50)
print(f"📦 Produits : {curseur.execute('SELECT COUNT(*) FROM produits').fetchone()[0]}")
print(f"👥 Clients : {curseur.execute('SELECT COUNT(*) FROM clients').fetchone()[0]}")
print(f"🛒 Ventes : {curseur.execute('SELECT COUNT(*) FROM ventes').fetchone()[0]}")
print(f"💳 Paiements : {curseur.execute('SELECT COUNT(*) FROM paiements').fetchone()[0]}")
print("="*50)
print("\n👉 Maintenant, rafraîchis ton Tableau de Bord (F5)")
print("   pour voir les graphiques se remplir ! 📊")

conn.close()