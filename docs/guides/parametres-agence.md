# Guide — Paramètres de l'agence

Ce guide explique comment configurer l'identité visuelle de votre agence. Ces informations apparaissent dans le cartouche de chaque rapport PDF généré par ArchiClaude.

---

## 1. Accéder aux paramètres

Depuis n'importe quelle page de l'application :
1. Cliquez sur le lien **Paramètres de l'agence** dans le menu de navigation, ou
2. Accédez directement à l'URL http://localhost:3010/agency.

La page **Identité visuelle & cartouche** s'affiche.

---

## 2. Remplir les informations

Complétez les champs du formulaire :

| Champ | Description | Exemple |
|---|---|---|
| Nom de l'agence | Raison sociale ou nom commercial | Promo IDF SARL |
| Adresse | Adresse postale complète | 15 rue Pillet-Will, 75009 Paris |
| Téléphone | Numéro de contact | +33 1 42 00 00 00 |
| E-mail | Adresse de contact | contact@promoidf.fr |
| Site web | URL du site (optionnel) | https://promoidf.fr |
| SIRET | Numéro d'identification (optionnel) | 123 456 789 00012 |

Tous les champs sont optionnels mais il est recommandé de remplir au minimum le nom de l'agence et l'adresse pour des rapports professionnels.

---

## 3. Uploader le logo

1. Dans la section **Logo**, cliquez sur **Choisir un fichier**.
2. Sélectionnez une image au format PNG, JPG ou SVG.
   - Taille recommandée : 400 × 120 px minimum
   - Fond transparent recommandé (PNG ou SVG)
   - Taille maximale : 2 Mo
3. Cliquez sur **Uploader**.

Le logo apparaît dans la prévisualisation du cartouche dès l'upload confirmé.

Pour supprimer le logo actuel, cliquez sur l'icône de suppression à côté de l'aperçu.

---

## 4. Choisir la couleur

1. Dans la section **Couleur principale**, cliquez sur le sélecteur de couleur.
2. Entrez un code hexadécimal (exemple : `#1e40af` pour un bleu foncé) ou utilisez le color picker.
3. La couleur est appliquée à l'en-tête du cartouche et aux éléments d'accentuation du rapport PDF.

Choisissez une couleur avec un contraste suffisant sur fond blanc (ratio WCAG AA ≥ 4,5:1 recommandé).

---

## 5. Prévisualiser

La section **Prévisualisation du cartouche** affiche en temps réel le rendu du cartouche tel qu'il apparaîtra dans les rapports PDF :
- Logo à gauche
- Nom et coordonnées de l'agence à droite
- Bande de couleur principale en en-tête

Vérifiez que toutes les informations sont lisibles et correctement positionnées.

---

## Enregistrer les modifications

Cliquez sur **Enregistrer** en bas du formulaire.

Une notification de confirmation apparaît en bas de l'écran. Les modifications sont immédiatement prises en compte pour les prochains rapports générés.

Les rapports PDF déjà générés ne sont pas modifiés rétroactivement.

---

## Questions fréquentes

**Mon logo apparaît trop grand ou mal cadré.**
Recadrez votre image à un ratio 3:1 (largeur × hauteur) avant de l'uploader. Les formats SVG s'adaptent mieux aux différentes tailles.

**Comment revenir à la couleur par défaut ?**
Entrez `#1e3a5f` dans le champ couleur (bleu ArchiClaude par défaut) ou effacez le champ et enregistrez.

**Les informations de l'agence sont-elles partagées entre utilisateurs ?**
Oui. Les paramètres de l'agence sont communs à tous les utilisateurs du compte. Tout membre ayant accès à l'application peut les modifier.
