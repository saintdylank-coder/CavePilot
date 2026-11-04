# On importe le module sqlite3 qui est déjà dans Python
import sqlite3

# 1. On se connecte à la base de données (cela crée le fichier cave.db)
connexion = sqlite3.connect('cave.db')
curseur = connexion.cursor()

# 2. On crée la table "produits" (comme l'onglet de ton Excel)
curseur.execute('''
    CREATE TABLE IF NOT EXISTS produits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        categorie TEXT NOT NULL,
        prix_achat REAL,
        prix_vente_hall REAL,
        seuil_alerte INTEGER DEFAULT 5
    )
''')

# 3. On crée la table "stocks" (pour savoir où est le produit : Magasin ou Hall)
curseur.execute('''
    CREATE TABLE IF NOT EXISTS stocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produit_id INTEGER,
        emplacement TEXT NOT NULL,
        quantite INTEGER DEFAULT 0,
        FOREIGN KEY (produit_id) REFERENCES produits(id)
    )
''')

# 4. On crée la table "utilisateurs" (pour les accès)
curseur.execute('''
    CREATE TABLE IF NOT EXISTS utilisateurs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        role TEXT NOT NULL,
        mot_de_passe TEXT NOT NULL,
        actif INTEGER DEFAULT 1
    )
''')

# 5. On sauvegarde les modifications et on ferme la connexion
connexion.commit()
connexion.close()

print("✅ Base de données 'cave.db' créée avec succès !")