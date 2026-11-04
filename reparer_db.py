import sqlite3
import os

# 1. On vérifie où Python cherche la base de données
chemin_complet = os.path.abspath('cave.db')
print(f"📍 Python va modifier le fichier situé ici : {chemin_complet}")

# 2. On se connecte à la base
conn = sqlite3.connect('cave.db')
curseur = conn.cursor()

# 3. Liste des colonnes qu'il nous faut dans la table 'ventes'
commandes_sql = [
    "ALTER TABLE ventes ADD COLUMN total REAL DEFAULT 0",
    "ALTER TABLE ventes ADD COLUMN mode_paiement TEXT DEFAULT 'especes'",
    "ALTER TABLE ventes ADD COLUMN client_id INTEGER",
    "ALTER TABLE ventes ADD COLUMN emplacement_vente TEXT DEFAULT 'Hall'",
    "ALTER TABLE ventes ADD COLUMN caissier_id INTEGER DEFAULT 1"
]

# 4. On essaie d'ajouter chaque colonne une par une
for sql in commandes_sql:
    try:
        curseur.execute(sql)
        print(f"✅ Colonne ajoutée avec succès !")
    except Exception as e:
        # Si la colonne existe déjà, Python l'ignore et continue
        print(f"⏭️ Cette colonne existe déjà, on passe à la suivante.")

# 5. On sauvegarde et on ferme
conn.commit()
conn.close()

print("\n🎉 Réparation terminée ! Tu peux relancer ton site (python app.py).")