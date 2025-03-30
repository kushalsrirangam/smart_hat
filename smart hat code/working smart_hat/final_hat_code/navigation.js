let map, directionsService, directionsRenderer, userLocation, watchId;
let routeSteps = [], currentStepIndex = 0, pathLine;
let trackingPaused = false;
const proximityThreshold = 25;
const pathHistory = [];

let arrowMarker = null;
let blueDot = null;

// 🔊 Send voice message to Flask server (to be spoken on phone)
function pushMessageToFlask(message) {
  fetch("/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message })
  });
}

function initMap() {
  navigator.geolocation.getCurrentPosition((pos) => {
    userLocation = {
      lat: pos.coords.latitude,
      lng: pos.coords.longitude
    };
    map = new google.maps.Map(document.getElementById("map"), {
      center: userLocation,
      zoom: 18,
      mapTypeId: "roadmap",
      rotateControl: true
    });
    directionsService = new google.maps.DirectionsService();
    directionsRenderer = new google.maps.DirectionsRenderer({ map });

    pushMessageToFlask("Map ready. Please search a destination or use voice.");
  });
}

function startVoiceSearch() {
  const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
  recognition.lang = 'en-US';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onresult = function (event) {
    const voiceText = event.results[0][0].transcript.toLowerCase().trim();
    console.log("🎤 Heard:", voiceText);

    if (voiceText.includes("where am i")) {
      speakDetailedLocation();
      return;
    }

    const pattern = /(?:go to|navigate to|find|search for|take me to|get directions to|head to)?\s*(.*)$/;
    const match = voiceText.match(pattern);
    let destination = match && match[1] ? match[1].trim() : "";

    if (destination && destination.length > 2) {
      document.getElementById("destinationInput").value = destination;
      pushMessageToFlask(`Getting directions to ${destination}`);
      routeTo(destination);
    } else {
      pushMessageToFlask("Say something like 'navigate to library' or 'where am I'.");
    }
  };

  recognition.onerror = (event) => {
    console.error("Voice recognition error:", event.error);
    pushMessageToFlask("Sorry, I didn't catch that.");
  };

  recognition.start();
}

function speakDetailedLocation() {
  if (!navigator.geolocation) return pushMessageToFlask("Geolocation not supported.");

  navigator.geolocation.getCurrentPosition((position) => {
    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    const geocoder = new google.maps.Geocoder();
    const latLng = new google.maps.LatLng(lat, lng);

    geocoder.geocode({ location: latLng }, (results, status) => {
      if (status === "OK" && results[0]) {
        pushMessageToFlask(`You are at ${results[0].formatted_address}`);
      } else {
        pushMessageToFlask(`Latitude ${lat}, Longitude ${lng}.`);
      }
    });
  }, () => pushMessageToFlask("Unable to get your current location."));
}

function routeTo(place) {
  if (!map || !directionsService || !directionsRenderer || !userLocation) {
    pushMessageToFlask("Navigation not ready.");
    return;
  }

  const service = new google.maps.places.PlacesService(map);
  service.findPlaceFromQuery({ query: place, fields: ["geometry", "name"] }, (results, status) => {
    if (status === google.maps.places.PlacesServiceStatus.OK && results[0]) {
      const location = results[0].geometry.location;
      const request = {
        origin: userLocation,
        destination: location,
        travelMode: google.maps.TravelMode.WALKING
      };

      directionsService.route(request, (result, status) => {
        if (status === "OK") {
          directionsRenderer.setDirections(result);
          routeSteps = result.routes[0].legs[0].steps;
          currentStepIndex = 0;
          pathLine = new google.maps.Polyline({ path: [], map, strokeColor: '#00ffc8' });
          startLiveTracking();
        } else {
          fallbackGeocode(place);
        }
      });
    } else {
      fallbackGeocode(place);
    }
  });
}

function fallbackGeocode(place) {
  pushMessageToFlask("Couldn't get route. Showing location on map.");
  const geocoder = new google.maps.Geocoder();
  geocoder.geocode({ address: place }, (res, status) => {
    if (status === "OK" && res[0]) {
      map.setCenter(res[0].geometry.location);
      new google.maps.Marker({ map, position: res[0].geometry.location });
    } else {
      pushMessageToFlask("Still couldn’t find that location.");
    }
  });
}

function startLiveTracking() {
  if (!navigator.geolocation) return pushMessageToFlask("Geolocation not supported.");

  if (watchId) navigator.geolocation.clearWatch(watchId);
  watchId = navigator.geolocation.watchPosition((pos) => {
    if (trackingPaused) return;

    const heading = pos.coords.heading || 0;
    const newPos = { lat: pos.coords.latitude, lng: pos.coords.longitude };
    userLocation = newPos;

    map.setCenter(newPos);
    map.setZoom(18);
    map.setHeading(heading); // Optional: rotate map

    // 🔵 Blue Dot
    if (!blueDot) {
      blueDot = new google.maps.Marker({
        position: newPos,
        map,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 8,
          fillColor: '#4285F4',
          fillOpacity: 1,
          strokeWeight: 2,
          strokeColor: 'white'
        }
      });
    } else {
      blueDot.setPosition(newPos);
    }

    // 🧭 Rotating Arrow
    if (!arrowMarker) {
      arrowMarker = new google.maps.Marker({
        position: newPos,
        map,
        icon: {
          path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
          scale: 5,
          strokeColor: "#00ffc8",
          fillOpacity: 1,
          rotation: heading
        }
      });
    } else {
      arrowMarker.setPosition(newPos);
      arrowMarker.setIcon({
        ...arrowMarker.getIcon(),
        rotation: heading
      });
    }

    const path = pathLine.getPath();
    path.push(newPos);
    pathHistory.push(newPos);
    savePathToFirebase(newPos);

    if (routeSteps.length && currentStepIndex < routeSteps.length) {
      const step = routeSteps[currentStepIndex];
      const userLatLng = new google.maps.LatLng(newPos.lat, newPos.lng);
      const stepStart = new google.maps.LatLng(step.start_location.lat(), step.start_location.lng());

      const dist = google.maps.geometry.spherical.computeDistanceBetween(userLatLng, stepStart);

      if (dist < proximityThreshold) {
        let instruction = step.instructions.replace(/<[^>]+>/g, '').toLowerCase();

        if (instruction.startsWith("head ")) instruction = "Go forward";
        else if (instruction.includes("turn left")) instruction = "Turn left";
        else if (instruction.includes("turn right")) instruction = "Turn right";
        else if (instruction.includes("continue")) instruction = "Keep walking straight";
        else if (instruction.includes("your destination")) instruction = "You have reached your destination";
        else instruction = instruction.charAt(0).toUpperCase() + instruction.slice(1);

        const next = routeSteps[currentStepIndex + 1];
        const remaining = next ? google.maps.geometry.spherical.computeDistanceBetween(
          userLatLng,
          new google.maps.LatLng(next.start_location.lat(), next.start_location.lng())
        ) : 0;

        pushMessageToFlask(`${instruction}. Next in ${Math.round(remaining)} meters.`);
        currentStepIndex++;
      }
    }

  }, () => pushMessageToFlask("Unable to track your location."), {
    enableHighAccuracy: true,
    maximumAge: 1000,
    timeout: 10000
  });
}

function toggleTracking() {
  trackingPaused = !trackingPaused;
  pushMessageToFlask(trackingPaused ? "Navigation paused." : "Navigation resumed.");
}

function savePathToFirebase(pos) {
  fetch('/log_location', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat: pos.lat, lng: pos.lng, timestamp: Date.now() })
  });
}
