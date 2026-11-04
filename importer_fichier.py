import sqlite3
import pandas as pd

print("📖 Lecture du fichier Excel...")

# Lire le fichier Excel sans en-tête pour d'abord trouver la bonne ligne
df_brut = pd.read_excel('FICHIER DE SUIVI DE STOCK 10 0CT 26.xlsx', 
                        sheet_name='RECAP MENSUEL', 
                        header=None)

# Chercher la ligne qui contient "CATÉGORIE" et "PRODUIT"
ligne_en_tete = None
for i in range(len(df_brut)):
    premiere_colonne = str(df_brut.iloc[i, 0]).upper()
    if 'CATÉGORIE' in premiere_colonne or 'CATEGORIE' in premiere_colonne:
        ligne_en_tete = i
        break

if ligne_en_tete is None:
    print("❌ Erreur : Impossible de trouver la ligne d'en-tête avec 'CATÉGORIE'")
    print("Premières lignes du fichier :")
    print(df_brut.head(10))
    exit()

print(f"✅ Ligne d'en-tête trouvée à la ligne {ligne_en_tete + 1}")

# Relire le fichier avec le bon en-tête
df = pd.read_excel('FICHIER DE SUIVI DE STOCK 10 0CT 26.xlsx', 
                   sheet_name='RECAP MENSUEL', 
                   header=ligne_en_tete)

print(f"📋 Colonnes trouvées : {list(df.columns)}")

# Nettoyer les noms de colonnes (enlever les espaces et mettre en majuscules)
df.columns = [str(col).strip().upper() for col in df.columns]

# Trouver les colonnes importantes
colonne_categorie = None
colonne_produit = None
colonne_prix = None
colonne_stock_initial = None

for col in df.columns:
    if 'CAT' in col:
        colonne_categorie = col
    elif 'PRODUIT' in col:
        colonne_produit = col
    elif 'PRIX' in col:
        colonne_prix = col
    elif 'STOCK' in col and 'INITIAL' in col:
        colonne_stock_initial = col

print(f"✅ Colonne catégorie : {colonne_categorie}")
print(f"✅ Colonne produit : {colonne_produit}")
print(f"✅ Colonne prix : {colonne_prix}")
print(f"✅ Colonne stock initial : {colonne_stock_initial}")

if not colonne_produit:
    print("❌ Erreur : Impossible de trouver la colonne PRODUIT")
    exit()

# Supprimer les lignes vides
df = df.dropna(subset=[colonne_produit])

# Exclure les lignes qui sont des titres de catégorie ou des totaux
mots_a_exclure = ['AUTRES BOISSONS', 'VINS BLANCS', 'CHAMPAGNES', 'TOTAUX', 'CATÉGORIE', 'NAN']
df = df[~df[colonne_produit].astype(str).str.upper().str.contains('|'.join(mots_a_exclure), na=False)]

print(f"✅ {len(df)} produits trouvés après filtrage")

# Se connecter à la base de données
connexion = sqlite3.connect('cave.db')
curseur = connexion.cursor()

compteur = 0

for index, row in df.iterrows():
    # Récupérer le nom du produit
    produit = str(row[colonne_produit]).strip()
    
    # Récupérer la catégorie
    categorie = 'DIVERS'
    if colonne_categorie and pd.notna(row[colonne_categorie]):
        cat = str(row[colonne_categorie]).strip().upper()
        if 'AUTRE' in cat:
            categorie = 'AUTRES'
        elif 'VIN' in cat:
            categorie = 'VINS'
        elif 'CHAMPAGNE' in cat or 'SPIRITUEUX' in cat:
            categorie = 'CHAMPAGNES'
        else:
            categorie = cat
    
    # Récupérer le prix (nettoyer "FCFA" et les espaces)
    prix = 0
    if colonne_prix and pd.notna(row[colonne_prix]):
        prix_texte = str(row[colonne_prix]).replace('FCFA', '').replace(',', '').replace(' ', '').strip()
        try:
            prix = int(float(prix_texte))
        except:
            prix = 0
    
    # Récupérer le stock initial
    stock_initial = 0
    if colonne_stock_initial and pd.notna(row[colonne_stock_initial]):
        try:
            stock_initial = int(float(str(row[colonne_stock_initial]).replace(',', '').strip()))
        except:
            stock_initial = 0
    
    # Insérer le produit dans la table 'produits'
    curseur.execute('''
        INSERT OR IGNORE INTO produits (nom, categorie, prix_achat, prix_vente_hall, seuil_alerte)
        VALUES (?, ?, ?, ?, 5)
    ''', (produit, categorie, prix, prix))
    
    # Récupérer l'ID du produit
    curseur.execute('SELECT id FROM produits WHERE nom = ?', (produit,))
    resultat = curseur.fetchone()
    
    if resultat:
        produit_id = resultat[0]
        
        # Insérer le stock initial dans la table 'stocks'
        if stock_initial > 0:
            curseur.execute('''
                INSERT INTO stocks (produit_id, emplacement, quantite)
                VALUES (?, 'Hall', ?)
            ''', (produit_id, stock_initial))
        
        compteur += 1

# Sauvegarder et fermer
connexion.commit()
connexion.close()

print(f"\n🎉 {compteur} produits importés avec succès !")
print("👉 Rafraîchis ta page web (F5) pour voir les produits.")