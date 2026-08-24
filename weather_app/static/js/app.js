(() => {
  "use strict";

  const SKY_EMOJI = {
    clear: "☀️",
    partly_cloudy: "🌤️",
    mostly_cloudy: "⛅",
    cloudy: "☁️",
    rain: "🌧️",
    showers: "🌦️",
    snow: "❄️",
  };

  const STORAGE_KEYS = {
    location: "weather.lastLocationId",
    favorites: "weather.favorites",
  };

  const state = {
    locationId: safeGet(STORAGE_KEYS.location) || "seoul",
    favorites: safeGetJSON(STORAGE_KEYS.favorites) || [],
    allLocations: [],
    lastAlertKey: null,
    notifyTimer: null,
  };

  const el = (id) => document.getElementById(id);

  function safeGet(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }
  function safeSet(key, value) {
    try { localStorage.setItem(key, value); } catch { /* ignore (private mode etc.) */ }
  }
  function safeGetJSON(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
  }

  // -- view / tab switching -------------------------------------------

  function showView(viewId) {
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    el(viewId).classList.remove("hidden");
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.view === viewId);
    });
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      showView(tab.dataset.view);
      if (tab.dataset.view === "locationsView") renderLocationsView();
    });
  });

  el("locationBtn").addEventListener("click", () => {
    showView("locationsView");
    document.querySelector('.tab[data-view="locationsView"]').classList.add("active");
    document.querySelector('.tab[data-view="homeView"]').classList.remove("active");
    renderLocationsView();
  });

  el("refreshBtn").addEventListener("click", () => {
    el("refreshBtn").classList.add("spinning");
    loadWeather().finally(() => el("refreshBtn").classList.remove("spinning"));
  });

  // -- data loading ------------------------------------------------------

  async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`request failed: ${res.status}`);
    return res.json();
  }

  async function loadLocations() {
    state.allLocations = await fetchJSON("/api/locations");
  }

  async function loadWeather() {
    try {
      const data = await fetchJSON(`/api/weather?location_id=${encodeURIComponent(state.locationId)}`);
      renderWeather(data);
      checkAlertsForNotification(data);
    } catch (err) {
      el("currentSky").textContent = "날씨 정보를 불러오지 못했습니다";
      console.error(err);
    }
  }

  // -- rendering -----------------------------------------------------

  function gradeClass(grade) {
    return {
      "좋음": "grade-good",
      "보통": "grade-warn",
      "나쁨": "grade-bad",
      "매우나쁨": "grade-severe",
    }[grade] || "";
  }

  function renderWeather(data) {
    const loc = data.location;
    const cur = data.current;

    el("locationName").textContent = loc.name;

    el("currentIcon").textContent = SKY_EMOJI[cur.sky_code] || "🌡️";
    el("currentTemp").textContent = cur.temp != null ? `${Math.round(cur.temp)}°` : "--°";
    el("currentSky").textContent = cur.sky || "-";
    el("currentFeels").textContent = cur.feels_like != null ? `체감 ${Math.round(cur.feels_like)}°` : "";
    el("currentUpdated").textContent = cur.updated_at ? `업데이트: ${formatTime(cur.updated_at)}` : "";

    el("statFeels").textContent = cur.feels_like != null ? `${cur.feels_like}°` : "-";
    el("statHumidity").textContent = cur.humidity != null ? `${cur.humidity}%` : "-";
    el("statWind").textContent = cur.wind_speed != null ? `${cur.wind_dir || ""} ${cur.wind_speed}m/s` : "-";
    el("statPrecip").textContent = cur.precip_prob != null ? `${cur.precip_prob}%` : "-";

    const pm10El = el("statPm10");
    pm10El.textContent = cur.pm10 != null ? `${cur.pm10} (${cur.pm10_grade})` : "정보없음";
    pm10El.className = `stat-value ${gradeClass(cur.pm10_grade)}`;

    const pm25El = el("statPm25");
    pm25El.textContent = cur.pm25 != null ? `${cur.pm25} (${cur.pm25_grade})` : "정보없음";
    pm25El.className = `stat-value ${gradeClass(cur.pm25_grade)}`;

    renderAlerts(data.alerts || []);
    renderHourly(data.hourly || []);
    renderDaily(data.daily || []);

    el("providerBadge").textContent = `제공: ${providerLabel(data.provider)}`;
  }

  function providerLabel(name) {
    if (!name) return "-";
    if (name.startsWith("accuweather")) return "AccuWeather";
    if (name.startsWith("kma")) return "기상청";
    return "샘플 데이터 (mock)";
  }

  function renderAlerts(alerts) {
    const banner = el("alertBanner");
    if (!alerts.length) {
      banner.classList.add("hidden");
      banner.innerHTML = "";
      return;
    }
    banner.classList.remove("hidden");
    banner.innerHTML = alerts
      .map(
        (a) => `<div class="alert-item">⚠️ [${escapeHtml(a.level || "특보")}] ${escapeHtml(a.title || "")}
          <span class="alert-desc">${escapeHtml(a.description || "")}</span></div>`
      )
      .join("");
  }

  function renderHourly(hourly) {
    const strip = el("hourlyStrip");
    strip.innerHTML = hourly
      .slice(0, 24)
      .map(
        (h) => `<div class="hourly-item">
          <div class="h-time">${escapeHtml(h.time)}</div>
          <div class="h-icon">${SKY_EMOJI[h.sky_code] || "🌡️"}</div>
          <div class="h-temp">${h.temp != null ? Math.round(h.temp) : "-"}°</div>
          <div class="h-pop">${h.precip_prob != null ? h.precip_prob : 0}%</div>
        </div>`
      )
      .join("");
  }

  function renderDaily(daily) {
    const list = el("dailyList");
    if (!daily.length) {
      list.innerHTML = '<div class="empty-hint">예보 정보가 없습니다</div>';
      return;
    }
    const temps = daily.flatMap((d) => [d.temp_min, d.temp_max]).filter((v) => v != null);
    const globalMin = Math.min(...temps);
    const globalMax = Math.max(...temps);
    const range = Math.max(1, globalMax - globalMin);

    list.innerHTML = daily
      .map((d) => {
        const min = d.temp_min != null ? Math.round(d.temp_min) : null;
        const max = d.temp_max != null ? Math.round(d.temp_max) : null;
        const leftPct = min != null ? ((min - globalMin) / range) * 100 : 0;
        const widthPct = min != null && max != null ? ((max - min) / range) * 100 : 100;
        return `<div class="daily-row">
          <div class="daily-label">${escapeHtml(d.label)}</div>
          <div class="daily-icons">${SKY_EMOJI[iconFromLabel(d.sky_am)] || "🌡️"}</div>
          <div class="daily-range">
            <span class="daily-min">${min != null ? min + "°" : "-"}</span>
            <span class="daily-bar" style="margin-left:${leftPct}%; width:${widthPct}%"></span>
            <span class="daily-max">${max != null ? max + "°" : "-"}</span>
          </div>
          <div class="daily-pop">${d.precip_prob_am != null ? d.precip_prob_am : 0}%</div>
        </div>`;
      })
      .join("");
  }

  function iconFromLabel(label) {
    const map = { "맑음": "clear", "구름많음": "mostly_cloudy", "구름조금": "partly_cloudy", "흐림": "cloudy", "비": "rain", "소나기": "showers", "눈": "snow" };
    return map[label] || null;
  }

  function formatTime(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
    } catch {
      return iso;
    }
  }

  function escapeHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // -- locations view --------------------------------------------------

  function renderLocationsView() {
    const favSet = new Set(state.favorites);
    const favList = state.allLocations.filter((l) => favSet.has(l.id));
    el("favoritesList").innerHTML = favList.length
      ? favList.map(locationRow).join("")
      : '<div class="empty-hint">즐겨찾기한 지역이 없습니다. 별표를 눌러 추가하세요.</div>';

    el("allLocationsList").innerHTML = state.allLocations.map(locationRow).join("");

    bindLocationRows();
  }

  function locationRow(loc) {
    const starred = state.favorites.includes(loc.id) ? "starred" : "";
    return `<div class="location-row" data-id="${loc.id}">
      <div class="loc-main">
        <span>${escapeHtml(loc.name)}</span>
        <span class="loc-en">${escapeHtml(loc.name_en)}</span>
      </div>
      <button class="star-btn ${starred}" data-star="${loc.id}">★</button>
    </div>`;
  }

  function bindLocationRows() {
    document.querySelectorAll(".location-row .loc-main").forEach((elm) => {
      elm.addEventListener("click", () => {
        const row = elm.closest(".location-row");
        selectLocation(row.dataset.id);
      });
    });
    document.querySelectorAll("[data-star]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleFavorite(btn.dataset.star);
      });
    });
  }

  function toggleFavorite(id) {
    const idx = state.favorites.indexOf(id);
    if (idx >= 0) state.favorites.splice(idx, 1);
    else state.favorites.push(id);
    safeSet(STORAGE_KEYS.favorites, JSON.stringify(state.favorites));
    renderLocationsView();
  }

  function selectLocation(id) {
    state.locationId = id;
    safeSet(STORAGE_KEYS.location, id);
    showView("homeView");
    document.querySelector('.tab[data-view="homeView"]').classList.add("active");
    document.querySelector('.tab[data-view="locationsView"]').classList.remove("active");
    loadWeather();
  }

  el("searchInput").addEventListener("input", async (e) => {
    const q = e.target.value.trim();
    try {
      state.allLocations = await fetchJSON(`/api/locations?q=${encodeURIComponent(q)}`);
    } catch {
      /* keep previous list on transient failure */
    }
    renderLocationsView();
  });

  // -- settings / notifications ----------------------------------------

  el("notifyBtn").addEventListener("click", async () => {
    if (!("Notification" in window)) {
      el("notifyStatus").textContent = "이 브라우저는 알림을 지원하지 않습니다.";
      return;
    }
    const perm = await Notification.requestPermission();
    updateNotifyStatus(perm);
    if (perm === "granted") startAlertPolling();
  });

  function updateNotifyStatus(perm) {
    const labels = { granted: "알림이 켜져 있습니다 ✅", denied: "알림이 차단되었습니다. iOS 설정 > 알림에서 허용해주세요.", default: "알림 권한이 아직 요청되지 않았습니다." };
    el("notifyStatus").textContent = labels[perm] || "";
  }

  function checkAlertsForNotification(data) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const alerts = data.alerts || [];
    if (!alerts.length) return;
    const key = alerts.map((a) => `${a.title}:${a.issued_at}`).join("|");
    if (key === state.lastAlertKey) return; // avoid repeat notifications for the same alert
    state.lastAlertKey = key;
    alerts.forEach((a) => {
      new Notification(`⚠️ ${data.location.name} ${a.title || "기상특보"}`, {
        body: a.description || "",
        tag: "weather-alert",
      });
    });
  }

  function startAlertPolling() {
    if (state.notifyTimer) clearInterval(state.notifyTimer);
    // Foreground polling only: iOS installed-PWA background web push needs a
    // push server, which is out of scope here (see README).
    state.notifyTimer = setInterval(loadWeather, 5 * 60 * 1000);
  }

  async function renderProviderInfo() {
    try {
      const health = await fetchJSON("/api/health");
      el("providerInfo").textContent = `사용 가능: ${health.providers.map(providerLabel).join(", ")}`;
    } catch {
      el("providerInfo").textContent = "제공처 정보를 불러오지 못했습니다.";
    }
  }

  // -- boot --------------------------------------------------------------

  async function boot() {
    if ("Notification" in window) updateNotifyStatus(Notification.permission);
    if ("Notification" in window && Notification.permission === "granted") startAlertPolling();

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }

    await loadLocations();
    renderProviderInfo();
    await loadWeather();
  }

  boot();
})();
