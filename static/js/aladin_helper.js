var aladin_oid = document.getElementById('aladin-oid').innerText;
var aladin_coord = document.getElementById('aladin-coord').innerText;
var aladin_ra = parseFloat(document.getElementById('aladin-ra').innerText);
var aladin_dec = parseFloat(document.getElementById('aladin-dec').innerText);

var aladin = A.aladin(
    '#aladin-lite-div',
    {survey: "P/DSS/color", fov: 2.0 / 60.0, target: aladin_coord}
);
var marker = A.marker(
    aladin_ra,
    aladin_dec,
    {popupTitle: aladin_oid}
);
var markerLayer = A.catalog();
aladin.addCatalog(markerLayer);
markerLayer.addSources([marker]);
