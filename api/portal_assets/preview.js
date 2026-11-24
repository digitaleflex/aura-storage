// L'extrait gratuit reste dans le lecteur : pas de « Enregistrer sous… » au clic droit.
// Ce n'est pas une protection contre un utilisateur déterminé (le réseau reste
// observable), mais le téléchargement du livre entier est bloqué côté serveur.
(function () {
  var audios = document.querySelectorAll('audio[src^="/extrait/"]');
  for (var i = 0; i < audios.length; i++) {
    audios[i].setAttribute('controlsList', 'nodownload');
    audios[i].setAttribute('disablePictureInPicture', '');
    audios[i].addEventListener('contextmenu', function (event) {
      event.preventDefault();
    });
  }
})();
