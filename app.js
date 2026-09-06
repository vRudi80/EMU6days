let chart, raceData;

const $ = id => document.getElementById(id);
const colors = [
  "#38bdf8","#f472b6","#a78bfa","#34d399","#fbbf24","#fb7185",
  "#60a5fa","#c084fc","#2dd4bf","#f97316","#4ade80","#e879f9",
  "#22d3ee","#facc15","#818cf8","#fb923c","#4ade80","#f43f5e"
];

async function load() {
  const r = await fetch("data/race.json?ts=" + Date.now(), {cache:"no-store"});
  if (!r.ok) throw new Error("A race.json nem tölthető be.");
  raceData = await r.json();
  initializeTimeRange();
  render();
}

function countryCode(value) {
  return String(value ?? "").trim().toUpperCase().substring(0, 3);
}

function isHungarian(value) {
  const country = String(value ?? "").trim().toUpperCase();
  return country === "HUN" || country.startsWith("HUN_") || country.startsWith("HUN-");
}

function filteredAthletes() {
  const search = $("search").value.trim().toLowerCase();
  const hu = $("hungarians").checked;

  let a = raceData.athletes.filter(x => {
    const matchesSearch = !search ||
      String(x.name ?? "").toLowerCase().includes(search) ||
      String(x.bib ?? "").includes(search);
    const matchesCountry = !hu || isHungarian(x.country);
    return matchesSearch && matchesCountry;
  });

  a.sort((x,y) => Number(y.km) - Number(x.km));
  const limit = Number($("limit").value);
  return limit ? a.slice(0, limit) : a;
}

function getAllTimes() {
  return raceData.athletes.flatMap(a => (a.points || []).map(p => new Date(p.t).getTime()))
    .filter(Number.isFinite);
}

function initializeTimeRange() {
  const times = getAllTimes();
  if (!times.length) return;
  const min = new Date(Math.min(...times));
  const max = new Date(Math.max(...times));
  $("rangeStart").value = toDateTimeLocal(min);
  $("rangeEnd").value = toDateTimeLocal(max);
}

function toDateTimeLocal(date) {
  const pad = n => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function getChartRange() {
  const mode = $("timeRange").value;
  const times = getAllTimes();
  if (!times.length) return {};

  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);

  if (mode === "full") {
    return {min: minTime, max: maxTime};
  }

  if (mode === "24h") {
    return {min: Math.max(minTime, maxTime - 24 * 60 * 60 * 1000), max: maxTime};
  }

  const start = new Date($("rangeStart").value).getTime();
  const end = new Date($("rangeEnd").value).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return {};
  return {min: start, max: end};
}

function render() {
  const athletes = filteredAthletes();
  drawChart(athletes);
  drawTable(athletes);
  $("status").textContent = `${raceData.athletes.length} versenyző · ${raceData.updatedAt ? "frissítve " + new Date(raceData.updatedAt).toLocaleString("hu-HU") : "nincs frissítési idő"}`;
  $("updated").textContent = raceData.updatedAt ? "Utolsó adatfrissítés: " + new Date(raceData.updatedAt).toLocaleString("hu-HU") : "";
}

function drawChart(athletes) {
  const ctx = $("raceChart").getContext("2d");
  if (chart) chart.destroy();
  const datasets = athletes.map((a,i) => ({
    label: a.name,
    data: a.points,
    parsing: {xAxisKey:"t", yAxisKey:"km"},
    borderColor: colors[i % colors.length],
    backgroundColor: colors[i % colors.length],
    borderWidth: i < 5 ? 2.7 : 1.5,
    pointRadius: 0,
    pointHitRadius: 8,
    tension: 0,
    spanGaps: true
  }));
  const range = getChartRange();

  chart = new Chart(ctx,{
    type:"line",
    data:{datasets},
    options:{
      responsive:true, maintainAspectRatio:false,
      interaction:{mode:"nearest",intersect:false},
      plugins:{
        legend:{position:"bottom",labels:{color:"#cbd5e1",usePointStyle:true,padding:14}},
        tooltip:{callbacks:{
          title: items => items[0]?.raw ? new Date(items[0].raw.t).toLocaleString("hu-HU") : "",
          label: item => `${item.dataset.label}: ${Number(item.raw.km).toFixed(1)} km`
        }}
      },
      scales:{
        x:{type:"time",min:range.min,max:range.max,time:{unit:"hour",displayFormats:{hour:"d. HH:mm"}},ticks:{color:"#94a3b8"},grid:{color:"#1f2b40"},title:{display:true,text:"Idő",color:"#94a3b8"}},
        y:{beginAtZero:true,ticks:{color:"#94a3b8",callback:v=>v+" km"},grid:{color:"#1f2b40"},title:{display:true,text:"Megtett táv",color:"#94a3b8"}}
      }
    }
  });
}

// Chart.js time scale needs a date adapter. Load it once dynamically.
if (!window._adapterLoaded) {
  window._adapterLoaded = true;
  const s=document.createElement("script");
  s.src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js";
  s.onload=load; document.head.appendChild(s);
} else load();

function drawTable(athletes) {
  $("ranking").innerHTML = athletes.map((a,i)=>`<tr>
    <td>${i+1}</td><td><strong>${escapeHtml(a.name)}</strong> <span class="muted">#${a.bib}</span></td>
    <td>${escapeHtml(countryCode(a.country))}</td><td>${escapeHtml(a.category||"")}</td>
    <td>${a.laps}</td><td>${Number(a.km).toFixed(3)}</td>
    <td>${escapeHtml(a.lastLap||"")}</td><td>${a.lastReadTime ? new Date(a.lastReadTime).toLocaleString("hu-HU") : ""}</td>
  </tr>`).join("");
}

function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}

$("search").addEventListener("input", render);
$("limit").addEventListener("change", render);
$("hungarians").addEventListener("change", render);
$("timeRange").addEventListener("change", () => {
  $("customRange").hidden = $("timeRange").value !== "custom";
  if ($("timeRange").value === "custom") initializeTimeRange();
  render();
});
$("applyRange").addEventListener("click", render);
$("reset").addEventListener("click",()=>{
  $("search").value="";
  $("limit").value="20";
  $("hungarians").checked=false;
  $("timeRange").value="24h";
  $("customRange").hidden=true;
  initializeTimeRange();
  render();
});
