/* ES5: all external requests run on the host, not on the legacy tablet. */
(function () {
  'use strict';
  var current = {available: false, location: 'LOCATING...'}, generation = 0, photoKey = '';
  window.robcoWeather = function () { return current; };
  function get(url, done) {
    var xhr = new XMLHttpRequest(), finished = false;
    var timer = setTimeout(function () { finish(null); xhr.abort(); }, 45000);
    function finish(value) { if (finished) { return; } finished = true; clearTimeout(timer); done(value); }
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) { return; }
      var data = null;
      try { if (xhr.status === 200) { data = JSON.parse(xhr.responseText); } } catch (e) {}
      finish(data);
    };
    try { xhr.open('GET', url, true); xhr.send(null); } catch (e) { finish(null); }
  }
  function photo(city, region, token) {
    get('/api/city-photo?city=' + encodeURIComponent(city) + '&region=' + encodeURIComponent(region || ''), function (data) {
      if (token !== generation) { return; }
      var image = data && (data.image_url || data.photo);
      if (data && data.available && /^(\/api\/city-photo\/image\?|data:image\/jpeg;base64,)/.test(image)) {
        current.photo = image; current.photo_source = data.source;
        current.photo_title = data.landmark || data.title;
      } else {
        setTimeout(function () { if (token === generation) { photo(city, region, token); } }, 60000);
      }
    });
  }
  function locate(coords) {
    var token = ++generation;
    photoKey = '';
    var url = '/api/local-weather';
    if (coords) { url += '?lat=' + coords.latitude + '&lon=' + coords.longitude; }
    function refresh() {
      get(url, function (data) {
        if (token !== generation) { return; }
        if (data && data.available) {
          var key = data.location + ':' + data.region;
          if (key === photoKey) {
            data.photo = current.photo; data.photo_source = current.photo_source; data.photo_title = current.photo_title;
          }
          current = data;
          if (key !== photoKey) { photoKey = key; photo(data.location, data.region, token); }
        } else if (coords) {
          locate(null); return;
        } else if (!current.available) {
          current = data || {available: false, location: 'RETRYING...'};
        } else { current.stale = true; }
        setTimeout(function () { if (token === generation) { refresh(); } }, data && data.available ? 600000 : 30000);
      });
    }
    refresh();
  }
  locate(null);
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(function (position) { locate(position.coords); }, function () {}, {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
  }
}());
