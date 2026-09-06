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
  render();
}

function filteredAthletes() {
  const search = $("search").value.trim().toLowerCase();
  const hu = $("hungarians").checked;
  let a = raceData.athletes.filter(x =>
    (!search || x.name.toLowerCase().includes(search) || String(x.bib).includes(search)) &&
    (!hu || x.country === "HUN")
  );
  a.sort((x,y) => y.km - x.km);
  const limit = Number($("limit").value);
  return limit ? a.slice(0,limit) : a;
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
        x:{type:"time",time:{unit:"hour",displayFormats:{hour:"d. HH:mm"}},ticks:{color:"#94a3b8"},grid:{color:"#1f2b40"},title:{display:true,text:"Idő",color:"#94a3b8"}},
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
    <td>${a.country||""}</td><td>${a.category||""}</td>
    <td>${a.laps}</td><td>${Number(a.km).toFixed(3)}</td>
    <td>${a.lastLap||""}</td><td>${a.lastReadTime ? new Date(a.lastReadTime).toLocaleString("hu-HU") : ""}</td>
  </tr>`).join("");
}
function escapeHtml(s){return s.replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}
["search","limit","hungarians"].forEach(id=>$(id).addEventListener("input",render));
$("reset").addEventListener("click",()=>{$("search").value="";$("limit").value="20";$("hungarians").checked=false;render()});
