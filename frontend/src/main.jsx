import React, {useEffect,useRef,useState} from 'react'
import { createRoot } from 'react-dom/client'
import L from 'leaflet'
const API = import.meta.env.VITE_API || 'http://localhost:8000'

function App(){
  const mapRef=useRef(null); const [map,setMap]=useState(null)
  const [bikes,setBikes]=useState([]); const [nearest,setNearest]=useState(null)
  const [user,setUser]=useState({lat: -37.8136, lon: 144.9631}); const [route,setRoute]=useState(null)
  const [weather,setWeather]=useState(null); const [toast,setToast]=useState(null)

  useEffect(()=>{ const m=L.map('map').setView([user.lat,user.lon],13)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(m); setMap(m)
    return ()=>m.remove()
  },[])
  useEffect(()=>{ if(!map) return; const click=e=>setUser({lat:e.latlng.lat,lon:e.latlng.lng}); map.on('click',click); return ()=>map.off('click',click) },[map])

  async function refresh(){
    try{
      const r=await fetch(`${API}/devices?near=${user.lat},${user.lon}&limit=200`); const j=await r.json()
      setBikes(j.items||[]); setNearest(j.nearest_device||null)
      const w=await (await fetch(`${API}/weather/current?lat=${user.lat}&lon=${user.lon}`)).json(); setWeather(w)
    }catch{ setToast('Failed to refresh devices') }
  }
  useEffect(()=>{ refresh() },[user.lat,user.lon])

  useEffect(()=>{ if(!map) return; const layer=L.layerGroup().addTo(map)
    bikes.forEach(b=>{ const mk=L.circleMarker([b.lat||0,b.lon||0],{radius:6}); mk.bindTooltip(`${b.id} (${b.lock_state})`); layer.addLayer(mk) })
    if(nearest) L.circle([nearest.lat,nearest.lon],{radius:50}).addTo(layer)
    return ()=>layer.remove()
  },[map,bikes,nearest])

  async function findNearestAndRoute(){
    if(!nearest) { setToast('No nearby bikes'); return }
    const r=await fetch(`${API}/route/plan`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({from:{lat:user.lat,lon:user.lon},to:{lat:nearest.lat,lon:nearest.lon}})})
    setRoute(await r.json())
  }
  useEffect(()=>{ if(!map||!route) return; const coords=(route.path||[]).map(p=>[p.lat,p.lon]); const poly=L.polyline(coords).addTo(map); return ()=>poly.remove() },[map,route])

  return (
  <div>
    <div id="map" style={{ height: "100vh", width: "100%" }}></div>

    <div
    style={{
        position: "absolute",
        top: 10,
        left: 10,
        background: "#fff",
        padding: "10px",
        borderRadius: "8px",
        boxShadow: "0 2px 10px rgba(0,0,0,.15)",
        zIndex: 1000
    }}
    >
    <b>Micromobility</b>
    <div>User @ {user.lat.toFixed(4)},{user.lon.toFixed(4)}</div>
    <button onClick={refresh}>Refresh</button>
    <button onClick={findNearestAndRoute}>Find nearest & route</button>
    {weather && (
        <div>
        Weather: {weather.condition} | wind {weather.wind} m/s | factor{" "}
        {weather.speed_factor}
        </div>
    )}
    {/* {route && (
        <div>
        Distance: {route.distance_m} m | ETA: {route.total_eta_s}s (base{" "}
        {route.base_eta_s}s + {route.weather_eta_s}s)
        </div>
    )} */}
    {route && route.steps && (
    <ol style={{marginTop:8}}>
      {route.steps.map((s,i)=>(
        <li key={i}>
          step {i+1}: {Math.round(s.time_s)} s, ~{s.distance_m} m
        </li>
      ))}
    </ol>
  )}
    </div>


    {toast && <div style={{
      position: "absolute", right: 10, bottom: 10,
      background: "#333", color: "#fff",
      padding: "8px 12px", borderRadius: 6
    }}>{toast}</div>}
  </div>
)

}
createRoot(document.getElementById('root')).render(<App/>)
