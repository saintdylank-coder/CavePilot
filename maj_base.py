# ============================================
# MISE À JOUR DE LA BASE DE DONNÉES
# Ajout des colonnes et tables pour :
# - Prix Bar et Prix Kit
# - Gestion des Clients (crédits)
# - Journal des Ventes
# - Mouvements de Stock
# ============================================

import sqlite3

print("🔧 Mise à jour de la base de données en cours...\n")

connexion = sqlite3.connect('cave.db')
curseur = connexion.cursor()

# ============================================
# 1. AJOUT DES COLONNES PRIX_BAR ET PRIX_KIT
# ============================================
print("📦 1/4 - Ajout des colonnes prix_bar et prix_kit dans la table produits...")

try:
    # Ajouter prix_bar (par défaut = prix_vente_hall, car toutes les boissons ont un prix bar)
    curseur.execute("""
        ALTER TABLE produits 
        ADD COLUMN prix_bar INTEGER DEFAULT 0
    """)
    print("   ✅ Colonne 'prix_bar' ajoutée")
except Exception as e:
    if "duplicate column" in str(e).lower():
        print("   ℹ️  Colonne 'prix_bar' existe déjà")
    else:
        print(f"   ❌ Erreur : {e}")

try:
    # Ajouter prix_kit (par défaut = NULL, car seulement certains produits sont en kit)
    curseur.execute("""
        ALTER TABLE produits 
        ADD COLUMN prix_kit INTEGER DEFAULT NULL
    """)
    print("   ✅ Colonne 'prix_kit' ajoutée")
except Exception as e:
    if "duplicate column" in str(e).lower():
        print("   ℹ️  Colonne 'prix_kit' existe déjà")
    else:
        print(f"   ❌ Erreur : {e}")

# Mettre à jour prix_bar = prix_vente_hall pour tous les produits existants
# (car toutes les boissons ont un prix bar, par défaut identique au prix hall)
curseur.execute("""
    UPDATE produits 
    SET prix_bar = prix_vente_hall 
    WHERE prix_bar = 0 OR prix_bar IS NULL
""")
print(f"   📊 {curseur.rowcount} produits mis à jour avec prix_bar = prix_hall")

connexion.commit()

# ============================================
# 2. CRÉATION DE LA TABLE CLIENTS
# ============================================
print("\n👥 2/4 - Création de la table 'clients'...")

curseur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL UNIQUE,
        telephone TEXT,
        solde_du INTEGER DEFAULT 0,
        date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actif INTEGER DEFAULT 1
    )
""")
connexion.commit()
print("   ✅ Table 'clients' créée (ou déjà existante)")

# ============================================
# 3. CRÉATION DE LA TABLE VENTES (le grand cahier)
# ============================================
print("\n📒 3/4 - Création de la table 'ventes'...")

curseur.execute("""
    CREATE TABLE IF NOT EXISTS ventes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_heure TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        produit_id INTEGER NOT NULL,
        type_vente TEXT NOT NULL CHECK(type_vente IN ('hall', 'kit', 'bar', 'commande')),
        quantite INTEGER NOT NULL,
        prix_applique INTEGER NOT NULL,
        montant INTEGER NOT NULL,
        mode_paiement TEXT DEFAULT 'especes' CHECK(mode_paiement IN ('especes', 'credit')),
        client_id INTEGER,
        FOREIGN KEY (produit_id) REFERENCES produits(id),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    )
""")
connexion.commit()
print("   ✅ Table 'ventes' créée (ou déjà existante)")

# ============================================
# 4. CRÉATION DE LA TABLE MOUVEMENTS_STOCK
# ============================================
print("\n🔄 4/4 - Création de la table 'mouvements_stock'...")

curseur.execute("""
    CREATE TABLE IF NOT EXISTS mouvements_stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_heure TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        produit_id INTEGER NOT NULL,
        type_mouvement TEXT NOT NULL,
        quantite INTEGER NOT NULL,
        emplacement TEXT NOT NULL,
        reference_vente_id INTEGER,
        FOREIGN KEY (produit_id) REFERENCES produits(id),
        FOREIGN KEY (reference_vente_id) REFERENCES ventes(id)
    )
""")
connexion.commit()
print("   ✅ Table 'mouvements_stock' créée (ou déjà existante)")

# ============================================
# RÉCAPITULATIF
# ============================================
connexion.close()

print("\n" + "="*50)
print("✅ MISE À JOUR TERMINÉE AVEC SUCCÈS !")
print("="*50)
print("\n📋 Récapitulatif :")
print("   • Table 'produits' : colonnes prix_bar et prix_kit ajoutées")
print("   • Table 'clients' : créée pour gérer les crédits")
print("   • Table 'ventes' : créée pour enregistrer toutes les ventes")
print("   • Table 'mouvements_stock' : créée pour tracer les sorties")
print("\n👉 Prochaine étape : Modifier l'onglet Produits pour")
print("   renseigner les prix bar et kit de chaque boisson.")