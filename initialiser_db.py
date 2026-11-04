import sqlite3

# Nom du fichier de notre base de données
FICHIER_DB = 'cave.db'

def initialiser_base_de_donnees():
    print("🔄 Connexion à la base de données...")
    # Cela crée le fichier cave.db s'il n'existe pas encore
    connexion = sqlite3.connect(FICHIER_DB)
    curseur = connexion.cursor()
    
    print("📦 Création de la table 'produits'...")
    # Table qui contient la liste de tes boissons
    curseur.execute('''
        CREATE TABLE IF NOT EXISTS produits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            categorie TEXT NOT NULL,
            prix_unitaire REAL NOT NULL
        )
    ''')
    
    print("🔄 Création de la table 'mouvements'...")
    # Table qui enregistre chaque mouvement (stock initial, entrée, sortie) avec sa date
    curseur.execute('''
        CREATE TABLE IF NOT EXISTS mouvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            produit_id INTEGER,
            type_mouvement TEXT NOT NULL,  -- 'INITIAL', 'ENTREE', ou 'SORTIE'
            quantite INTEGER NOT NULL,
            FOREIGN KEY (produit_id) REFERENCES produits (id)
        )
    ''')
    
    # Sauvegarder les modifications et fermer la connexion
    connexion.commit()
    connexion.close()
    print("✅ Base de données initialisée avec succès ! Le fichier 'cave.db' est prêt.")

# Ce bloc permet de lancer la fonction quand on exécute le script
if __name__ == '__main__':
    initialiser_base_de_donnees()