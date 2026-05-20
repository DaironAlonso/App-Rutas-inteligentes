
import React, { useState, useEffect } from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, 
  PieChart, Pie, Cell, LineChart, Line, AreaChart, Area 
} from 'recharts';
import { 
  Upload, Settings, Map as MapIcon, FileText, AlertCircle, 
  CheckCircle2, Clock, MapPin, Navigation, Truck, 
  ChevronRight, Download, BarChart3, Info, Calculator
} from 'lucide-react';
import * as xlsx from 'xlsx';
import { MapContainer, TileLayer, Marker, Popup, Polyline, GeoJSON, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { BusinessRules, ProcessingResult, PDV, DailyRoute, RouteStop } from './types';
import { format } from 'date-fns';

// Fix for default marker icons in Leaflet + React
import L from 'leaflet';
// @ts-ignore
import icon from 'leaflet/dist/images/marker-icon.png';
// @ts-ignore
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41]
});
L.Marker.prototype.options.icon = DefaultIcon;

// Component to handle auto-zooming to routes
function MapBoundsHandler({ filteredRoutes }: { filteredRoutes: any[] }) {
  const map = useMap();

  useEffect(() => {
    if (filteredRoutes.length > 0) {
      const bounds = L.latLngBounds([]);
      filteredRoutes.forEach(r => {
        r.paradas.forEach((p: any) => {
          bounds.extend([p.pdv.latitud, p.pdv.longitud]);
        });
      });
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
      }
    }
  }, [filteredRoutes, map]);

  return null;
}

const DEFAULT_RULES: BusinessRules = {
  horaInicio: "08:00",
  horaFin: "18:00",
  almuerzoInicio: "12:00",
  almuerzoFin: "13:00",
  maxHorasDiarias: 9,
  maxHorasSemanales: 42,
  permanenciaDefaultMin: 40,
  distanciaCaminableKm: 0.8,
  velocidadCaminandoKmh: 4,
  velocidadBusKmh: 15,
  sabadoActivo: true,
  sabadoMaxPdvs: 2,
  sabadoPermanenciaFija: 198,
  maxRelocalizacionMin: 120,
  centroPunto: [4.6097, -74.0817]
};

export default function App() {
  const [activeTab, setActiveTab] = useState<'upload' | 'dashboard' | 'maps' | 'config' | 'omitted' | 'capacity'>('config');
  const [rules, setRules] = useState<BusinessRules>(DEFAULT_RULES);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressStatus, setProgressStatus] = useState('');
  const [result, setResult] = useState<ProcessingResult | null>(null);
  const [fileData, setFileData] = useState<any[] | null>(null);
  const [selectedRoute, setSelectedRoute] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState<number | null>(null);

  // Capacity Analysis State (Persistent)
  const [capacityPdvData, setCapacityPdvData] = useState<any[] | null>(null);
  const [capacityGroupBy, setCapacityGroupBy] = useState<'Ciudad' | 'Departamento'>('Ciudad');
  const [isCalculatingCapacity, setIsCalculatingCapacity] = useState(false);
  const [capacityProgress, setCapacityProgress] = useState(0);
  const [capacityStatus, setCapacityStatus] = useState('');
  const [capacityResult, setCapacityResult] = useState<any>(null);

  // Toast Notifications State
  const [toasts, setToasts] = useState<{ id: string; message: string; type: 'success' | 'error' | 'info' }[]>([]);
  
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  // Dark Mode Theme State
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    return localStorage.getItem('theme') === 'dark';
  });

  useEffect(() => {
    const root = window.document.documentElement;
    if (darkMode) {
      root.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      root.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }, [darkMode]);

  const processUploadedFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const bstr = evt.target?.result;
        const wb = xlsx.read(bstr, { type: 'binary' });
        const wsname = wb.SheetNames[0];
        const ws = wb.Sheets[wsname];
        const data = xlsx.utils.sheet_to_json(ws);
        setFileData(data);
        setActiveTab('upload');
        showToast('Archivo Excel cargado exitosamente', 'success');
      } catch (err: any) {
        showToast(`Error al leer archivo: ${err.message}`, 'error');
      }
    };
    reader.readAsBinaryString(file);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processUploadedFile(file);
  };

  const runProcessing = async () => {
    if (!fileData) return;
    setIsProcessing(true);
    setProgress(0);
    setProgressStatus('Iniciando...');
    
    const ws = xlsx.utils.json_to_sheet(fileData);
    const wb = xlsx.utils.book_new();
    xlsx.utils.book_append_sheet(wb, ws, "Data");
    const out = xlsx.write(wb, { type: 'base64', bookType: 'xlsx' });

    try {
      const startResp = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fileContent: out, rules })
      });
      
      if (!startResp.ok) {
        throw new Error(`Error de inicio: ${startResp.statusText}`);
      }
      
      const { sessionId } = await startResp.json();
      showToast('Tarea de optimización iniciada en segundo plano', 'info');

      // Server-Sent Events (SSE) Stream
      const eventSource = new EventSource(`/api/progress/stream/${sessionId}`);
      
      eventSource.onmessage = async (event) => {
        try {
          const status = JSON.parse(event.data);
          setProgress(status.progress);
          setProgressStatus(status.status);
          
          if (status.progress === 100) {
            eventSource.close();
            const finalResp = await fetch(`/api/results/${sessionId}`);
            const finalData = await finalResp.json();
            setResult(finalData);
            setIsProcessing(false);
            setActiveTab('dashboard');
            showToast('Optimización completada con éxito', 'success');
          } else if (status.status.startsWith('Error')) {
            eventSource.close();
            setIsProcessing(false);
            showToast(status.status, 'error');
          }
        } catch (err: any) {
          eventSource.close();
          setIsProcessing(false);
          showToast(`Error: ${err.message}`, 'error');
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        setIsProcessing(false);
        showToast('Error de conexión con el canal SSE', 'error');
      };

    } catch (err: any) {
      console.error(err);
      showToast(`Error: ${err.message}`, 'error');
      setIsProcessing(false);
    }
  };

  const downloadExcel = () => {
    if (!result) return;
    
    // Hoja 1: Itinerario Completo
    const ws_itinerary = xlsx.utils.json_to_sheet(result.rutas.flatMap(r => 
      r.paradas.map((p, index) => ({
        Dia: ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab'][r.dia],
        Ruta: r.rutaNombre,
        Orden_Visita: index + 1,
        PDV: p.pdv.pdv,
        Direccion: p.pdv.direccion,
        Llegada: p.horaLlegada,
        Salida: p.horaSalida,
        Transporte: p.tipoTransporte,
        Distancia_Tramo_Km: p.distanciaPreviaKm.toFixed(2),
        Tiempo_Traslado_Min: p.tiempoTrasladoMin.toFixed(0),
        Permanencia_Min: r.dia === 6 ? rules.sabadoPermanenciaFija : (p.pdv.tiempoVisita || rules.permanenciaDefaultMin)
      }))
    ));

    // Hoja 2: PDVs Omitidos
    const ws_omitted = xlsx.utils.json_to_sheet(result.omitidos.map(o => ({
      Dia: ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab'][o.dia],
      Ruta: o.pdv.ruta,
      PDV: o.pdv.pdv,
      Motivo: o.motivo,
      Coordenadas: `${o.pdv.latitud}, ${o.pdv.longitud}`
    })));

    const wb = xlsx.utils.book_new();
    xlsx.utils.book_append_sheet(wb, ws_itinerary, "Itinerarios");
    xlsx.utils.book_append_sheet(wb, ws_omitted, "PDVs_Omitidos");
    
    xlsx.writeFile(wb, `Planificacion_Global_Rutas_${format(new Date(), 'yyyyMMdd')}.xlsx`);
  };

  return (
    <div className="flex flex-col h-screen bg-slate-50 font-sans text-slate-900 overflow-hidden">
      {/* Toast Notifications */}
      <div className="fixed top-6 right-6 z-[200] flex flex-col gap-3 max-w-sm w-full pointer-events-none">
        {toasts.map((t) => (
          <div 
            key={t.id} 
            className={`p-4 rounded-xl shadow-xl border flex items-center gap-3 animate-in fade-in slide-in-from-top-4 duration-300 pointer-events-auto bg-white ${
              t.type === 'success' ? 'border-emerald-200 text-emerald-800' :
              t.type === 'error' ? 'border-red-200 text-red-800' : 'border-slate-200 text-slate-800'
            }`}
          >
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              t.type === 'success' ? 'bg-emerald-50 text-emerald-600' :
              t.type === 'error' ? 'bg-red-50 text-red-600' : 'bg-slate-50 text-slate-600'
            }`}>
              {t.type === 'success' ? <CheckCircle2 size={16} /> :
               t.type === 'error' ? <AlertCircle size={16} /> : <Info size={16} />}
            </div>
            <p className="text-xs font-semibold flex-1 leading-relaxed">{t.message}</p>
            <button 
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
              className="text-slate-400 hover:text-slate-600 font-bold text-sm px-1.5"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {/* Loading Overlay */}
      {isProcessing && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-md z-[100] flex items-center justify-center p-6">
          <div className="bg-white rounded-3xl shadow-2xl p-8 max-w-sm w-full text-center">
            <div className="relative w-24 h-24 mx-auto mb-6">
              <div className="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
              <div 
                className="absolute inset-0 border-4 border-indigo-600 rounded-full transition-all duration-500"
                style={{ 
                  clipPath: `inset(0 ${100 - progress}% 0 0)`,
                  transform: 'rotate(-90deg)' 
                }}
              ></div>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-xl font-black text-slate-800">{progress}%</span>
              </div>
            </div>
            <h3 className="text-xl font-bold text-slate-800 mb-2">Optimizando Rutas</h3>
            <p className="text-slate-500 text-sm mb-6">{progressStatus}</p>
            <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden mb-6">
              <div 
                className="bg-indigo-600 h-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              ></div>
            </div>
            <div className="flex items-center justify-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
              <div className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse"></div>
              Motor de Cálculo Activo
            </div>
          </div>
        </div>
      )}

      {/* Top Navigation */}
      <nav className="flex items-center justify-between px-6 py-3 bg-slate-900 text-white shrink-0 shadow-lg z-50">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-lg">S</div>
          <span className="text-lg font-semibold tracking-tight">SmartRoute <span className="text-indigo-400 font-normal">AI</span></span>
        </div>
        <div className="flex gap-6 text-sm font-medium text-slate-300">
          <span 
            onClick={() => setActiveTab('dashboard')} 
            className={`cursor-pointer transition-colors ${activeTab === 'dashboard' ? 'text-white underline underline-offset-8 decoration-indigo-500 decoration-2' : 'hover:text-white'}`}
          >
            Dashboard
          </span>
          <span 
            onClick={() => setActiveTab('upload')} 
            className={`cursor-pointer transition-colors ${activeTab === 'upload' ? 'text-white underline underline-offset-8 decoration-indigo-500 decoration-2' : 'hover:text-white'}`}
          >
            Carga
          </span>
          <span 
            onClick={() => setActiveTab('config')} 
            className={`cursor-pointer transition-colors ${activeTab === 'config' ? 'text-white underline underline-offset-8 decoration-indigo-500 decoration-2' : 'hover:text-white'}`}
          >
            Reglas
          </span>
          <span 
            onClick={() => setActiveTab('capacity')} 
            className={`cursor-pointer transition-colors ${activeTab === 'capacity' ? 'text-white underline underline-offset-8 decoration-indigo-500 decoration-2' : 'hover:text-white'}`}
          >
            Dimensionamiento
          </span>
          {result && (
            <>
              <span 
                onClick={() => setActiveTab('maps')} 
                className={`cursor-pointer transition-colors ${activeTab === 'maps' ? 'text-white underline underline-offset-8 decoration-indigo-500 decoration-2' : 'hover:text-white'}`}
              >
                Mapas
              </span>
              <span 
                onClick={() => setActiveTab('omitted')} 
                className={`cursor-pointer transition-colors ${activeTab === 'omitted' ? 'text-white underline underline-offset-8 decoration-indigo-500 decoration-2' : 'hover:text-white'}`}
              >
                Omitidos
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-4">
          <button 
            onClick={() => setDarkMode(!darkMode)}
            className="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white flex items-center justify-center transition-all cursor-pointer"
            title={darkMode ? "Modo Claro" : "Modo Oscuro"}
          >
            {darkMode ? '☀️' : '🌙'}
          </button>
          <div className="flex flex-col items-end">
            <span className="text-xs font-bold">Planificación Activa</span>
            <span className="text-[10px] text-indigo-400 uppercase tracking-widest">{format(new Date(), 'dd MMM yyyy')}</span>
          </div>
          <div className="w-8 h-8 bg-slate-700 rounded-full border border-slate-600 flex items-center justify-center text-xs font-bold">DR</div>
        </div>
      </nav>

      {/* Sub-Header */}
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between shrink-0">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-slate-400 font-bold mb-1">Estado del Sistema</div>
          <h1 className="text-xl font-bold text-slate-800">
            {activeTab === 'config' && 'Configuración de Reglas Operativas'}
            {activeTab === 'upload' && 'Gestión de Puntos de Venta (PDVs)'}
            {activeTab === 'dashboard' && 'Rendimiento y Cobertura'}
            {activeTab === 'maps' && 'Visualización Territorial'}
            {activeTab === 'omitted' && 'Análisis de Exclusiones'}
            {activeTab === 'capacity' && 'Cálculo de Capacidad Operativa'}
          </h1>
        </div>
        <div className="flex gap-3">
          {activeTab === 'capacity' && (
            <button 
              onClick={() => {
                const ws = xlsx.utils.json_to_sheet([
                  { PDV: 'Ejemplo 1', Direccion: 'Calle 123', Ciudad: 'Bogotá', Departamento: 'Cundinamarca', Latitud: 4.6097, Longitud: -74.0817, Frecuencia: 2, 'Tiempo de visita entero': 40 },
                  { PDV: 'Ejemplo 2', Direccion: 'Carrera 45', Ciudad: 'Medellín', Departamento: 'Antioquia', Latitud: 6.2442, Longitud: -75.5812, Frecuencia: 1, 'Tiempo de visita entero': 30 }
                ]);
                const wb = xlsx.utils.book_new();
                xlsx.utils.book_append_sheet(wb, ws, "Plantilla_Capacidad");
                xlsx.writeFile(wb, "Plantilla_Dimensionamiento_Personal.xlsx");
              }}
              className="px-4 py-2 border border-slate-300 rounded text-sm font-semibold hover:bg-slate-50 transition-all flex items-center gap-2"
            >
              <Download size={14} /> Descargar Plantilla
            </button>
          )}
          {result && activeTab !== 'capacity' && (
            <button 
              onClick={downloadExcel}
              className="px-4 py-2 border border-slate-300 rounded text-sm font-semibold hover:bg-slate-50 transition-all flex items-center gap-2"
            >
              <Download size={14} /> Exportar Global
            </button>
          )}
          <button 
            disabled={!fileData || isProcessing}
            onClick={runProcessing}
            className={`px-4 py-2 rounded text-sm font-semibold shadow-sm transition-all flex items-center gap-2 ${
              !fileData ? 'bg-slate-100 text-slate-400 cursor-not-allowed' : 'bg-indigo-600 text-white hover:bg-indigo-700 active:scale-95'
            }`}
          >
            {isProcessing ? 'Procesando...' : (result ? 'Volver a Optimizar' : 'Ejecutar Optimización')}
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-6 bg-slate-50">
        {/* Dynamic Views */}
        <div className="max-w-[1600px] mx-auto">
          {activeTab === 'config' && <ConfigView rules={rules} setRules={setRules} />}
          {activeTab === 'upload' && <UploadView fileData={fileData} handleFileUpload={handleFileUpload} processUploadedFile={processUploadedFile} />}
          {activeTab === 'dashboard' && result && result.summary && <DashboardView result={result} />}
          {activeTab === 'maps' && result && result.rutas && (
            <MapsView 
              result={result} 
              rules={rules}
              selectedRoute={selectedRoute} 
              setSelectedRoute={setSelectedRoute} 
              selectedDay={selectedDay} 
              setSelectedDay={setSelectedDay} 
              showToast={showToast}
            />
          )}
          {activeTab === 'omitted' && result && result.omitidos && <OmittedView omitidos={result.omitidos} />}
          {activeTab === 'capacity' && (
            <CapacityView 
              rules={rules} 
              setExternalResult={setResult} 
              setActiveTab={setActiveTab}
              data={capacityPdvData}
              setData={setCapacityPdvData}
              groupBy={capacityGroupBy}
              setGroupBy={setCapacityGroupBy}
              isCalculating={isCalculatingCapacity}
              setIsCalculating={setIsCalculatingCapacity}
              capacityProgress={capacityProgress}
              setCapacityProgress={setCapacityProgress}
              capacityStatus={capacityStatus}
              setCapacityStatus={setCapacityStatus}
              localResult={capacityResult}
              setLocalResult={setCapacityResult}
              showToast={showToast}
            />
          )}
          
          {!result && activeTab !== 'config' && activeTab !== 'upload' && (
            <div className="flex flex-col items-center justify-center p-20 text-slate-400">
              <AlertCircle size={48} className="mb-4 opacity-20" />
              <p className="font-semibold">Carga datos y ejecuta la optimización para ver resultados.</p>
            </div>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200 px-6 py-2 flex items-center justify-between shrink-0 text-[10px] text-slate-400 font-bold uppercase tracking-wider">
        <div className="flex gap-4">
          <span>Optimización: OR-Tools <span className="text-green-500 ml-1">●</span> Activo</span>
          <span>Geocálculo: Haversine/OSRM <span className="text-indigo-500 ml-1">●</span> Standby</span>
          <span className="hidden md:inline">Versión: 2.1.0-PROD</span>
        </div>
        <div className="italic font-normal capitalize">
          SmartRoute AI - Logística de Última Milla
        </div>
      </footer>
    </div>
  );
}

function NavItem({ active, onClick, icon, label }: any) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl font-medium transition-all ${
        active 
          ? 'bg-blue-50 text-blue-700' 
          : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
      }`}
    >
      <span className={active ? 'text-blue-600' : 'text-slate-400'}>{icon}</span>
      {label}
    </button>
  );
}

function ConfigView({ rules, setRules }: any) {
  const updateRule = (key: string, val: any) => setRules({ ...rules, [key]: val });
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <ConfigCard title="Jornada Laboral" icon={<Clock className="text-blue-500" />}>
        <Input label="Inicio Jornada" value={rules.horaInicio} onChange={e => updateRule('horaInicio', e.target.value)} type="time" />
        <Input label="Fin Jornada" value={rules.horaFin} onChange={e => updateRule('horaFin', e.target.value)} type="time" />
        <Input label="Máx Horas Diarias" value={rules.maxHorasDiarias} onChange={e => updateRule('maxHorasDiarias', Number(e.target.value))} type="number" />
      </ConfigCard>

      <ConfigCard title="Receso Almuerzo" icon={<Info className="text-orange-500" />}>
        <Input label="Inicio Almuerzo" value={rules.almuerzoInicio} onChange={e => updateRule('almuerzoInicio', e.target.value)} type="time" />
        <Input label="Fin Almuerzo" value={rules.almuerzoFin} onChange={e => updateRule('almuerzoFin', e.target.value)} type="time" />
      </ConfigCard>

      <ConfigCard title="Movilidad (A Pie)" icon={<Navigation className="text-emerald-500" />}>
        <Input label="Velocidad Caminando (KM/H)" value={rules.velocidadCaminandoKmh} onChange={e => updateRule('velocidadCaminandoKmh', Number(e.target.value))} step="0.1" type="number" />
        <Input label="Umbral Caminable Máximo (KM)" value={rules.distanciaCaminableKm} onChange={e => updateRule('distanciaCaminableKm', Number(e.target.value))} step="0.1" type="number" />
      </ConfigCard>

      <ConfigCard title="Sábados" icon={<CheckCircle2 className="text-indigo-500" />}>
        <div className="flex items-center gap-2 mb-4">
          <input type="checkbox" checked={rules.sabadoActivo} onChange={e => updateRule('sabadoActivo', e.target.checked)} className="rounded" />
          <label className="text-sm font-medium">Aplicar Restricciones de Sábado</label>
        </div>
        <Input label="Máx PDVs Sábado" value={rules.sabadoMaxPdvs} onChange={e => updateRule('sabadoMaxPdvs', Number(e.target.value))} type="number" />
        <Input label="Permanencia Fija (min)" value={rules.sabadoPermanenciaFija} onChange={e => updateRule('sabadoPermanenciaFija', Number(e.target.value))} type="number" />
      </ConfigCard>

      <ConfigCard title="Ubicación de Inicio" icon={<MapPin className="text-red-500" />}>
        <Input 
          label="Latitud Centro" 
          value={rules.centroPunto[0]} 
          onChange={e => updateRule('centroPunto', [Number(e.target.value), rules.centroPunto[1]])} 
          type="number" 
          step="0.000001" 
        />
        <Input 
          label="Longitud Centro" 
          value={rules.centroPunto[1]} 
          onChange={e => updateRule('centroPunto', [rules.centroPunto[0], Number(e.target.value)])} 
          type="number" 
          step="0.000001" 
        />
        <p className="text-[10px] text-slate-400 mt-2 italic">
          Coordenada base para el inicio de las rutas y centro del mapa exportado.
        </p>
      </ConfigCard>
    </div>
  );
}

function Input({ label, ...props }: any) {
  return (
    <div className="mb-4">
      <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">{label}</label>
      <input 
        {...props} 
        className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm font-semibold text-slate-700 focus:ring-2 focus:ring-indigo-500 hover:border-indigo-200 outline-none transition-all"
      />
    </div>
  );
}

function ConfigCard({ title, icon, children }: any) {
  return (
    <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center gap-2 mb-6">
        <div className="w-8 h-8 rounded-lg bg-slate-50 flex items-center justify-center">
          {React.cloneElement(icon, { size: 16 })}
        </div>
        <h3 className="font-bold text-slate-800 text-sm uppercase tracking-tight">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function UploadView({ fileData, handleFileUpload, processUploadedFile }: any) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      processUploadedFile(file);
    }
  };

  return (
    <div className="space-y-6">
      <div 
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`p-12 rounded-2xl border-2 border-dashed flex flex-col items-center justify-center text-center transition-all group ${
          isDragging 
            ? 'border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/20 scale-[1.01] shadow-lg' 
            : 'bg-white border-slate-200 hover:border-indigo-300'
        }`}
      >
        <div className="w-20 h-20 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform shadow-sm">
          <Upload size={40} />
        </div>
        <h3 className="text-xl font-bold text-slate-800 tracking-tight">Cargar Archivo Maestro de PDVs</h3>
        <p className="text-slate-500 max-w-sm mb-8 text-sm leading-relaxed">
          Sube o arrastra tu archivo Excel (.xlsx) con las columnas <span className="font-mono font-bold text-indigo-600">Latitud</span>, <span className="font-mono font-bold text-indigo-600">Longitud</span> y <span className="font-mono font-bold text-indigo-600">Ruta</span> para iniciar la optimización.
        </p>
        <label className="bg-slate-900 text-white px-8 py-3 rounded-xl font-bold cursor-pointer hover:bg-slate-800 shadow-lg active:scale-95 transition-all flex items-center gap-2">
          <FileText size={18} /> Seleccionar Archivo
          <input type="file" className="hidden" accept=".xlsx, .xls" onChange={handleFileUpload} />
        </label>
      </div>

      {fileData && (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
          <div className="p-4 bg-slate-50 border-b border-slate-200 flex justify-between items-center">
            <h4 className="font-bold text-slate-700 text-sm flex items-center gap-2">
              <BarChart3 size={16} className="text-slate-400" />
              Vista Previa de Datos ({fileData.length} registros)
            </h4>
            <div className="flex gap-4 text-[10px] font-bold uppercase tracking-widest text-emerald-600">
              <span className="flex items-center gap-1"><CheckCircle2 size={12}/> Estructura Válida</span>
            </div>
          </div>
          <div className="overflow-x-auto max-h-[400px] scrollbar-thin scrollbar-thumb-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="bg-white sticky top-0 border-b border-slate-100 z-10">
                <tr>
                  {Object.keys(fileData[0]).map(k => (
                    <th key={k} className="p-4 font-bold text-slate-400 text-[10px] uppercase tracking-widest bg-white">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {fileData.slice(0, 50).map((row, i) => (
                  <tr key={i} className="hover:bg-indigo-50/30 transition-colors">
                    {Object.values(row).map((v: any, j) => (
                      <td key={j} className="p-4 text-slate-600 font-medium whitespace-nowrap overflow-hidden text-ellipsis max-w-[200px]">
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function DashboardView({ result }: { result: ProcessingResult }) {
  const dataPie = [
    { name: 'Programados', value: result.summary.totalPdvs - result.omitidos.length },
    { name: 'Omitidos', value: result.omitidos.length },
  ];
  const COLORS = ['#4f46e5', '#f1f5f9'];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
      <StatCard label="PDVs Programados" value={(result.summary.totalPdvs - result.omitidos.length).toString()} icon={<CheckCircle2 className="text-emerald-500" />} color="emerald" />
      <StatCard label="Personal Requerido" value={(result.summary.personasRequeridas || Math.ceil(result.summary.totalRutas / 6)).toString()} icon={<Calculator size={18} className="text-indigo-500" />} color="indigo" />
      <StatCard label="Recorrido Total" value={`${result.summary.totalKm.toFixed(1)} KM`} icon={<Navigation className="text-blue-500" />} color="blue" />
      <StatCard label="Horas Operativas" value={`${result.summary.totalHoras.toFixed(1)} H`} icon={<Clock className="text-orange-500" />} color="orange" />

      <div className="lg:col-span-3 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <h4 className="font-bold flex items-center gap-2"><Truck size={18} className="text-slate-400"/> Km Recorridos por Jornada</h4>
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Semana Actual</span>
        </div>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={result.rutas.reduce((acc: any[], r) => {
              const day = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'][r.dia];
              const existing = acc.find(x => x.day === day);
              if (existing) existing.km += r.kmTotales;
              else acc.push({ day, km: r.kmTotales });
              return acc;
            }, [])}>
              <defs>
                <linearGradient id="colorKm" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.1}/>
                  <stop offset="95%" stopColor="#4f46e5" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
              <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 600}} />
              <YAxis axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 600}} />
              <Tooltip contentStyle={{borderRadius: '12px', border: 'none', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)'}} />
              <Area type="monotone" dataKey="km" stroke="#4f46e5" strokeWidth={3} fillOpacity={1} fill="url(#colorKm)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-slate-900 p-6 rounded-2xl shadow-xl flex flex-col items-center justify-center text-white">
        <h4 className="font-bold self-start mb-6 text-sm opacity-80 uppercase tracking-wider">Eficiencia de Planificación</h4>
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={dataPie} innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                <Cell fill="#6366f1" />
                <Cell fill="#1e293b" />
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="text-center mt-4">
          <span className="text-4xl font-black text-white">{result.summary.cobertura.toFixed(0)}%</span>
          <p className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest mt-1">Cumplimiento Objetivo</p>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon, color }: any) {
  const colors: any = {
    blue: 'bg-indigo-50 text-indigo-600 border-indigo-100',
    emerald: 'bg-emerald-50 text-emerald-600 border-emerald-100',
    orange: 'bg-orange-50 text-orange-600 border-orange-100',
    indigo: 'bg-slate-50 text-slate-600 border-slate-100'
  };
  return (
    <div className={`p-6 rounded-2xl border shadow-sm flex items-center gap-4 bg-white ${colors[color].split(' ')[2]}`}>
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${colors[color].split(' ').slice(0, 2).join(' ')}`}>
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{label}</p>
        <p className="text-2xl font-black text-slate-900 tracking-tight">{value}</p>
      </div>
    </div>
  );
}

function MapsView({ result, rules, selectedRoute, setSelectedRoute, selectedDay, setSelectedDay, showToast }: any) {
  const filteredRoutes = result.rutas.filter((r: any) => 
    (!selectedRoute || r.rutaNombre === selectedRoute) && (selectedDay === null || r.dia === selectedDay)
  );

  const downloadGeoJSON = () => {
    if (!result) return;
    
    const features: any[] = [];
    
    filteredRoutes.forEach((ruta: any) => {
      // 1. Generate Point features for each PDV
      ruta.paradas.forEach((stop: any, idx: number) => {
        features.push({
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [stop.pdv.longitud, stop.pdv.latitud]
          },
          properties: {
            pdv: stop.pdv.pdv,
            direccion: stop.pdv.direccion,
            ciudad: stop.pdv.ciudad,
            departamento: stop.pdv.departamento,
            orden: idx + 1,
            ruta: ruta.rutaNombre,
            dia: ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'][ruta.dia] || ruta.dia,
            horaLlegada: stop.horaLlegada,
            horaSalida: stop.horaSalida,
            tipoTransporte: stop.tipoTransporte,
            distanciaPreviaKm: stop.distanciaPreviaKm
          }
        });
        
        // 2. Generate line feature if geometry exists
        if (stop.geometry && stop.geometry.coordinates) {
          features.push({
            type: "Feature",
            geometry: stop.geometry,
            properties: {
              ruta: ruta.rutaNombre,
              dia: ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'][ruta.dia] || ruta.dia,
              tipoTransporte: stop.tipoTransporte,
              tramo: idx + 1,
              distanciaKm: stop.distanciaPreviaKm
            }
          });
        }
      });
    });
    
    const geojson = {
      type: "FeatureCollection",
      features: features
    };
    
    const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Planificacion_Rutas_${new Date().getTime()}.geojson`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Exportado GeoJSON exitosamente', 'success');
  };

  const downloadGPX = () => {
    if (!result) return;
    
    let gpx = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="SmartRoute AI" xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">
  <metadata>
    <name>SmartRoute AI Export</name>
    <desc>Rutas planificadas y optimizadas</desc>
    <time>${new Date().toISOString()}</time>
  </metadata>`;

    filteredRoutes.forEach((ruta: any) => {
      // Add waypoints for each PDV in the route
      ruta.paradas.forEach((stop: any, idx: number) => {
        gpx += `
  <wpt lat="${stop.pdv.latitud}" lon="${stop.pdv.longitud}">
    <name>${stop.pdv.pdv}</name>
    <desc>Orden: ${idx + 1} | Ruta: ${ruta.rutaNombre} | Llegada: ${stop.horaLlegada} | Salida: ${stop.horaSalida}</desc>
    <type>Address</type>
  </wpt>`;
      });
      
      // Add track for route paths
      gpx += `
  <trk>
    <name>${ruta.rutaNombre} - ${['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'][ruta.dia] || ruta.dia}</name>
    <desc>Distancia: ${ruta.kmTotales?.toFixed(2)} km</desc>
    <trkseg>`;
      
      ruta.paradas.forEach((stop: any) => {
        if (stop.geometry && stop.geometry.coordinates) {
          stop.geometry.coordinates.forEach((coord: number[]) => {
            gpx += `
      <trkpt lat="${coord[1]}" lon="${coord[0]}"></trkpt>`;
          });
        } else {
          gpx += `
      <trkpt lat="${stop.pdv.latitud}" lon="${stop.pdv.longitud}"></trkpt>`;
        }
      });
      
      gpx += `
    </trkseg>
  </trk>`;
    });
    
    gpx += `
</gpx>`;
    
    const blob = new Blob([gpx], { type: 'application/gpx+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Planificacion_Rutas_${new Date().getTime()}.gpx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Exportado GPX exitosamente', 'success');
  };

  const downloadDetailedRoutes = () => {
    if (!result) return;
    const data: any[] = [];
    result.rutas.forEach((ruta: any) => {
      ruta.paradas.forEach((stop: any, idx: number) => {
        data.push({
          'Ruta/Persona': ruta.rutaNombre,
          'Día': ['-', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'][ruta.dia] || ruta.dia,
          'Orden': idx + 1,
          'PDV': stop.pdv.pdv,
          'Dirección': stop.pdv.direccion,
          'Ciudad': stop.pdv.ciudad,
          'Llegada': stop.horaLlegada,
          'Salida': stop.horaSalida,
          'Tiempo Visita (min)': stop.pdv.tiempoVisita,
          'Km Recorridos': stop.distanciaPreviaKm.toFixed(2),
          'Latitud': stop.pdv.latitud,
          'Longitud': stop.pdv.longitud
        });
      });
    });

    const ws = xlsx.utils.json_to_sheet(data);
    const wb = xlsx.utils.book_new();
    xlsx.utils.book_append_sheet(wb, ws, "Rutero_Detallado");
    xlsx.writeFile(wb, `Rutero_Detalle_${new Date().getTime()}.xlsx`);
  };

  const downloadSelfContainedMap = () => {
    if (!result) return;
    
    const routesJson = JSON.stringify(result.rutas);
    const startPoint = rules?.centroPunto && (rules.centroPunto[0] !== 4.6097 || rules.centroPunto[1] !== -74.0817) 
      ? rules.centroPunto 
      : null;
    
    // In the HTML JS part, we'll calculate centroid if startPoint is null
    const htmlContent = `
<!DOCTYPE html>
<html>
<head>
    <title>Visualizador de Rutas Exportadas</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; height: 100vh; display: flex; flex-direction: column; }
        header { background: #1e293b; color: white; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; }
        .controls { background: #f8fafc; padding: 1rem 2rem; display: flex; gap: 1rem; border-bottom: 1px solid #e2e8f0; }
        select { padding: 0.5rem; border-radius: 0.5rem; border: 1px solid #cbd5e1; font-size: 0.875rem; min-width: 200px; }
        #map { flex: 1; width: 100%; }
        .legend { background: white; padding: 10px; border-radius: 5px; box-shadow: 0 0 15px rgba(0,0,0,0.2); line-height: 1.5; font-size: 12px; }
    </style>
</head>
<body>
    <header>
        <div style="font-weight: 800; font-size: 1.25rem;">Planeador de Rutas - Reporte Interactivo</div>
        <div style="font-size: 0.8rem; opacity: 0.7;">Generado el: ${new Date().toLocaleString()}</div>
    </header>
    <div class="controls">
        <select id="routeSelect">
            <option value="">Todas las Rutas</option>
        </select>
        <select id="daySelect">
            <option value="">Todos los Días</option>
            <option value="1">Lunes</option>
            <option value="2">Martes</option>
            <option value="3">Miércoles</option>
            <option value="4">Jueves</option>
            <option value="5">Viernes</option>
            <option value="6">Sábado</option>
        </select>
    </div>
    <div id="map"></div>

    <script>
        const routes = ${routesJson};
        const manualStartPoint = ${JSON.stringify(startPoint)};
        
        // Calculate dynamic center if no manual point is provided
        let calcCenter = [4.6097, -74.0817];
        if (!manualStartPoint) {
            let sumLat = 0, sumLng = 0, count = 0;
            routes.forEach(r => {
                r.paradas.forEach(s => {
                    sumLat += s.pdv.latitud;
                    sumLng += s.pdv.longitud;
                    count++;
                });
            });
            if (count > 0) calcCenter = [sumLat/count, sumLng/count];
        } else {
            calcCenter = manualStartPoint;
        }

        const map = L.map('map').setView(calcCenter, 12);
        
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);

        const routeColors = ['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];
        let activeLayers = L.featureGroup().addTo(map);

        // Populate route select
        const routeNames = [...new Set(routes.map(r => r.rutaNombre))];
        const routeSelect = document.getElementById('routeSelect');
        routeNames.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            routeSelect.appendChild(opt);
        });

        function render() {
            activeLayers.clearLayers();
            
            if (manualStartPoint) {
                L.marker(manualStartPoint, {
                    icon: L.divIcon({
                        html: '<div style="background:#1e293b; width:12px; height:12px; border-radius:50%; border:2px solid white;"></div>',
                        className: '',
                        iconSize: [12, 12]
                    })
                }).addTo(activeLayers).bindPopup('Punto de Inicio / Centro de Operaciones');
            }

            const selectedRoute = routeSelect.value;
            const selectedDay = daySelect.value;

            const filtered = routes.filter(r => {
                const routeMatch = !selectedRoute || r.rutaNombre === selectedRoute;
                const dayMatch = !selectedDay || r.dia == selectedDay;
                return routeMatch && dayMatch;
            });

            filtered.forEach((r, idx) => {
                const color = routeColors[idx % routeColors.length];
                
                r.paradas.forEach((stop, sIdx) => {
                    const pos = [stop.pdv.latitud, stop.pdv.longitud];
                    
                    const marker = L.circleMarker(pos, {
                        radius: 6,
                        fillColor: color,
                        color: "#fff",
                        weight: 2,
                        opacity: 1,
                        fillOpacity: 0.8
                    }).addTo(activeLayers);

                    marker.bindPopup(\`
                        <div style="font-family: sans-serif;">
                            <strong style="color: \${color};">\${stop.pdv.pdv}</strong><br/>
                            <div style="font-size: 11px; margin-top: 4px;">
                                <b>Orden:</b> \${sIdx + 1}<br/>
                                <b>Llegada:</b> \${stop.horaLlegada}<br/>
                                <b>Salida:</b> \${stop.horaSalida}<br/>
                                <b>Viaje:</b> \${stop.distanciaPreviaKm.toFixed(2)} km (\${stop.tiempoTrasladoMin.toFixed(0)} min)<br/>
                                <b>Dirección:</b> \${stop.pdv.direccion}
                            </div>
                        </div>
                    \`);

                    // Paint real road routes using polyline for better compatibility
                    if (stop.geometry && stop.geometry.coordinates) {
                        const latLngs = stop.geometry.coordinates.map(c => [c[1], c[0]]);
                        L.polyline(latLngs, {
                            color: color,
                            weight: 5,
                            opacity: 0.7,
                            dashArray: stop.tipoTransporte === 'pie' ? '5, 10' : null
                        }).addTo(activeLayers);
                    } else if (sIdx === 0 && manualStartPoint) {
                        // First stop to Depot
                        L.polyline([manualStartPoint, pos], { color: color, weight: 3, opacity: 0.4, dashArray: '5, 10' }).addTo(activeLayers);
                    } else if (sIdx > 0) {
                        // Fallback straight line between stops
                        const prevPos = [r.paradas[sIdx-1].pdv.latitud, r.paradas[sIdx-1].pdv.longitud];
                        L.polyline([prevPos, pos], { color: color, weight: 3, opacity: 0.4, dashArray: '5, 10' }).addTo(activeLayers);
                    }
                });
            });

            if (filtered.length > 0) {
                try {
                    map.fitBounds(activeLayers.getBounds(), { padding: [50, 50] });
                } catch(e) {}
            }
        }

        const daySelect = document.getElementById('daySelect');
        routeSelect.onchange = render;
        daySelect.onchange = render;
        
        render();
    </script>
</body>
</html>`;

    const blob = new Blob([htmlContent], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Mapa_Rutas_${new Date().getTime()}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const center: [number, number] = filteredRoutes[0]?.paradas[0] 
    ? [filteredRoutes[0].paradas[0].pdv.latitud, filteredRoutes[0].paradas[0].pdv.longitud] 
    : [4.570868, -74.297333]; 

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-280px)] min-h-[500px]">
      <div className="bg-white p-4 rounded-2xl border border-slate-200 flex flex-col gap-4 shadow-sm overflow-hidden">
        <div>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Filtro de Ruta</label>
            <div className="flex gap-1 flex-wrap">
              <button 
                onClick={downloadDetailedRoutes}
                className="flex items-center gap-1 text-[10px] font-bold text-indigo-600 hover:text-indigo-700 transition-colors bg-indigo-50 px-2 py-1 rounded cursor-pointer"
              >
                <Download size={10} /> EXCEL
              </button>
              <button 
                onClick={downloadSelfContainedMap}
                className="flex items-center gap-1 text-[10px] font-bold text-emerald-600 hover:text-emerald-700 transition-colors bg-emerald-50 px-2 py-1 rounded cursor-pointer"
              >
                <MapIcon size={10} /> MAP HTML
              </button>
              <button 
                onClick={downloadGeoJSON}
                className="flex items-center gap-1 text-[10px] font-bold text-sky-600 hover:text-sky-700 transition-colors bg-sky-50 px-2 py-1 rounded cursor-pointer"
              >
                <Download size={10} /> GEOJSON
              </button>
              <button 
                onClick={downloadGPX}
                className="flex items-center gap-1 text-[10px] font-bold text-amber-600 hover:text-amber-700 transition-colors bg-amber-50 px-2 py-1 rounded cursor-pointer"
              >
                <Download size={10} /> GPX
              </button>
            </div>
          </div>
          <select 
            value={selectedRoute || ''} 
            onChange={e => setSelectedRoute(e.target.value)}
            className="w-full p-2 bg-slate-50 border border-slate-200 rounded-lg outline-none text-sm font-semibold text-slate-700"
          >
            <option value="">Todas las rutas</option>
            {Array.from(new Set(result.rutas.map((r: any) => r.rutaNombre))).map((r: any) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2 block">Calendario Semanal</label>
          <div className="grid grid-cols-7 gap-1">
            <button 
              onClick={() => setSelectedDay(null)}
              className={`py-2 rounded-lg text-[10px] font-bold transition-all border ${
                selectedDay === null ? 'bg-indigo-600 text-white border-indigo-600 shadow-md' : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'
              }`}
            >
              TODOS
            </button>
            {[1,2,3,4,5,6].map(d => (
              <button 
                key={d}
                onClick={() => setSelectedDay(d)}
                className={`py-2 rounded-lg text-xs font-bold transition-all border ${
                  selectedDay === d ? 'bg-indigo-600 text-white border-indigo-600 shadow-md' : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {['', 'L', 'M', 'M', 'J', 'V', 'S'][d]}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto mt-2 space-y-2 pr-1">
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Secuencia de Visita</p>
          {filteredRoutes.flatMap((r: any) => r.paradas.map((p: any) => ({ ...p, dia: r.dia }))).map((p: any, i: number) => (
            <div key={i} className="p-3 bg-slate-50 rounded-xl border border-slate-100 flex items-center gap-3 hover:border-indigo-200 transition-colors cursor-default group">
              <div className="w-6 h-6 bg-white border border-slate-200 rounded-full flex items-center justify-center text-[10px] font-bold text-indigo-600 shadow-sm group-hover:bg-indigo-600 group-hover:text-white transition-colors">{i+1}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-bold truncate text-slate-800">{p.pdv.pdv}</p>
                  {selectedDay === null && (
                    <span className="text-[8px] font-black bg-slate-200 px-1 rounded text-slate-500">
                      {['', 'L', 'M', 'M', 'J', 'V', 'S'][p.dia]}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[9px] font-bold text-slate-400 flex items-center gap-1 uppercase tracking-tighter"><Clock size={10} className="text-indigo-400"/> {p.horaLlegada}-{p.horaSalida}</span>
                  <span className={`text-[9px] font-bold flex items-center gap-1 uppercase tracking-tighter ${p.tipoTransporte === 'pie' ? 'text-emerald-500' : 'text-blue-500'}`}>
                    {p.tipoTransporte === 'pie' ? <Navigation size={8} /> : <Truck size={8} />} {p.tipoTransporte}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="lg:col-span-3 bg-white rounded-2xl border border-slate-200 overflow-hidden relative shadow-inner z-10">
        <MapContainer center={center} zoom={13} style={{ height: '100%', width: '100%' }}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <MapBoundsHandler filteredRoutes={filteredRoutes} />
          {filteredRoutes.map((r: any) => (
            <React.Fragment key={`${r.rutaNombre}-${r.dia}`}>
              {r.paradas.map((p: any, i: number) => (
                <React.Fragment key={i}>
                  {p.geometry ? (
                    <GeoJSON 
                      key={`geo-${r.rutaNombre}-${i}-${p.pdv.id}`}
                      data={p.geometry} 
                      style={{ 
                        color: p.tipoTransporte === 'pie' ? '#10b981' : '#4f46e5', 
                        weight: p.tipoTransporte === 'pie' ? 5 : 4, 
                        opacity: 0.9,
                        dashArray: p.tipoTransporte === 'pie' ? '8, 12' : undefined
                      }} 
                    />
                  ) : (
                    i > 0 && (
                      <Polyline 
                        positions={[
                          [r.paradas[i-1].pdv.latitud, r.paradas[i-1].pdv.longitud],
                          [p.pdv.latitud, p.pdv.longitud]
                        ]} 
                        color={p.tipoTransporte === 'pie' ? '#10b981' : '#4f46e5'} 
                        weight={p.tipoTransporte === 'pie' ? 5 : 3} 
                        opacity={0.7} 
                        dashArray={p.tipoTransporte === 'pie' ? '8, 12' : undefined} 
                      />
                    )
                  )}
                  <Marker 
                    position={[p.pdv.latitud, p.pdv.longitud]}
                    icon={L.divIcon({
                      className: 'custom-div-icon',
                      html: `<div style="background-color: #4f46e5; color: white; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: bold; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3); line-height: 20px;">${i + 1}</div>`,
                      iconSize: [24, 24],
                      iconAnchor: [12, 12]
                    })}
                  >
                    <Popup>
                      <div className="p-1 min-w-[120px]">
                        <h5 className="font-bold text-indigo-600 m-0 text-xs tracking-tight uppercase">{p.pdv.pdv}</h5>
                        <p className="text-[10px] text-slate-500 m-0 mt-1 italic">{p.pdv.direccion}</p>
                        <div className="mt-2 border-t border-slate-100 pt-2 flex flex-col gap-1.5">
                          <div className="flex justify-between text-[9px] font-bold"><span className="text-slate-400 uppercase tracking-tighter">LLEGADA:</span> <span className="text-slate-800">{p.horaLlegada}</span></div>
                          <div className="flex justify-between text-[9px] font-bold"><span className="text-slate-400 uppercase tracking-tighter">SALIDA:</span> <span className="text-slate-800">{p.horaSalida}</span></div>
                          <div className="flex justify-between text-[9px] font-bold border-t border-slate-50 pt-1"><span className="text-slate-400 uppercase tracking-tighter">TRAMO:</span> <span className="text-indigo-600">{p.distanciaPreviaKm.toFixed(2)} KM</span></div>
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                </React.Fragment>
              ))}
            </React.Fragment>
          ))}
        </MapContainer>
        <div className="absolute top-4 right-4 z-20 flex flex-col gap-2">
           <div className="bg-white/80 backdrop-blur-sm px-3 py-1.5 rounded-lg border border-slate-200 shadow-sm text-[10px] font-bold uppercase tracking-widest text-slate-600">
             Zona: <span className="text-indigo-600 underline">Distrito Metropolitano</span>
           </div>
        </div>
      </div>
    </div>
  );
}

function OmittedView({ omitidos }: { omitidos: any[] }) {
  if (omitidos.length === 0) return (
    <div className="bg-white p-12 rounded-2xl border border-slate-200 text-center">
      <div className="w-16 h-16 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4">
        <CheckCircle2 size={32} />
      </div>
      <h3 className="text-lg font-bold">¡100% de Cumplimiento!</h3>
      <p className="text-slate-500">Todos los puntos de venta fueron programados exitosamente.</p>
    </div>
  );

  return (
    <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 border-b border-slate-100">
          <tr>
            <th className="p-4 font-bold text-slate-400">Día</th>
            <th className="p-4 font-bold text-slate-400">Ruta</th>
            <th className="p-4 font-bold text-slate-400">PDV</th>
            <th className="p-4 font-bold text-slate-400">Motivo de Omisión</th>
            <th className="p-4 font-bold text-slate-400">Coordenadas</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {omitidos.map((o, i) => (
            <tr key={i} className="hover:bg-slate-50/50">
              <td className="p-4 font-bold text-slate-600">{['', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sab'][o.dia]}</td>
              <td className="p-4 font-medium text-slate-700">{o.pdv.ruta}</td>
              <td className="p-4 text-slate-900 font-bold">{o.pdv.pdv}</td>
              <td className="p-4">
                <span className="px-3 py-1 bg-red-50 text-red-600 text-xs font-bold rounded-lg uppercase tracking-tight">{o.motivo}</span>
              </td>
              <td className="p-4 text-xs font-mono text-slate-400">{o.pdv.latitud.toFixed(4)}, {o.pdv.longitud.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CapacityView({ 
  rules, 
  setExternalResult, 
  setActiveTab,
  data,
  setData,
  groupBy,
  setGroupBy,
  isCalculating,
  setIsCalculating,
  capacityProgress,
  setCapacityProgress,
  capacityStatus,
  setCapacityStatus,
  localResult,
  setLocalResult,
  showToast
}: any) {
  const processFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const bstr = event.target?.result;
        const workbook = xlsx.read(bstr, { type: 'binary' });
        const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
        setData(xlsx.utils.sheet_to_json(firstSheet));
        showToast('Archivo de capacidad cargado exitosamente', 'success');
      } catch (err: any) {
        showToast(`Error al leer el archivo: ${err.message}`, 'error');
      }
    };
    reader.readAsBinaryString(file);
  };

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  };

  const runCapacityAnalysis = async () => {
    if (!data) return;
    setIsCalculating(true);
    setCapacityProgress(0);
    setCapacityStatus('Iniciando...');
    setLocalResult(null);
    
    try {
      console.log('Starting capacity analysis with:', { groupBy, pdvCount: data.length });
      const startResp = await fetch('/api/estimate-capacity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data, rules, groupBy })
      });
      
      if (!startResp.ok) {
        const text = await startResp.text();
        console.error('Server error response:', text);
        throw new Error(`Error del servidor: ${startResp.status} ${startResp.statusText}`);
      }

      const { sessionId } = await startResp.json();
      if (!sessionId) throw new Error('No se recibió Session ID');

      showToast('Tarea de dimensionamiento iniciada en segundo plano', 'info');

      // Server-Sent Events (SSE) Stream
      const eventSource = new EventSource(`/api/progress/stream/${sessionId}`);
      
      eventSource.onmessage = async (event) => {
        try {
          const status = JSON.parse(event.data);
          setCapacityProgress(status.progress);
          setCapacityStatus(status.status);
          
          if (status.progress === 100) {
            eventSource.close();
            const finalResp = await fetch(`/api/results/${sessionId}`);
            const finalData = await finalResp.json();
            setLocalResult(finalData);
            setExternalResult(finalData);
            setIsCalculating(false);
            showToast('Dimensionamiento completado con éxito', 'success');
          } else if (status.status.startsWith('Error')) {
            eventSource.close();
            setIsCalculating(false);
            showToast(status.status, 'error');
          }
        } catch (err: any) {
          eventSource.close();
          setIsCalculating(false);
          showToast(`Error: ${err.message}`, 'error');
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        setIsCalculating(false);
        showToast('Error de conexión con el canal SSE', 'error');
      };

    } catch (err: any) {
      console.error('Capacity Error:', err);
      showToast(`Error en el cálculo: ${err.message}`, 'error');
      setIsCalculating(false);
    }
  };

  const totals = data ? {
    pdvs: data.length,
    groups: new Set(data.map(d => d[groupBy] || 'Sin Definir')).size
  } : null;

  const result = localResult;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
            <h3 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
              <Settings size={16} className="text-indigo-500"/> Configuración
            </h3>
            
            <div className="space-y-4">
              <div>
                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-2">Agrupar Por</label>
                <div className="flex gap-2">
                  {(['Ciudad', 'Departamento'] as const).map(option => (
                    <button
                      key={option}
                      onClick={() => setGroupBy(option)}
                      className={`flex-1 py-2 rounded-lg text-xs font-bold border transition-all ${
                        groupBy === option 
                        ? 'bg-indigo-600 text-white border-indigo-600' 
                        : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              {!data ? (
                <label 
                  onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('border-indigo-500', 'bg-indigo-50/50'); }}
                  onDragLeave={(e) => { e.preventDefault(); e.currentTarget.classList.remove('border-indigo-500', 'bg-indigo-50/50'); }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.currentTarget.classList.remove('border-indigo-500', 'bg-indigo-50/50');
                    const file = e.dataTransfer.files?.[0];
                    if (file) processFile(file);
                  }}
                  className="w-full h-32 border-2 border-dashed border-slate-200 rounded-xl flex flex-col items-center justify-center cursor-pointer hover:border-indigo-300 transition-all bg-slate-50 group"
                >
                  <Upload size={24} className="text-slate-400 group-hover:text-indigo-500 mb-2 transition-colors"/>
                  <span className="text-xs font-bold text-slate-500 group-hover:text-indigo-600">Cargar / Arrastrar Archivo</span>
                  <input type="file" className="hidden" accept=".xlsx, .xls" onChange={handleUpload} />
                </label>
              ) : (
                <div className="p-4 bg-emerald-50 border border-emerald-100 rounded-xl">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-bold text-emerald-600 uppercase">Archivo Cargado</span>
                    <button onClick={() => setData(null)} className="text-[10px] font-bold text-emerald-700 underline">Cambiar</button>
                  </div>
                  <p className="text-xs font-bold text-emerald-800">{totals?.pdvs} PDVs detectados</p>
                  <p className="text-[10px] text-emerald-600 mt-1">{totals?.groups} {groupBy}(es) únicos</p>
                </div>
              )}

              <button 
                disabled={!data || isCalculating}
                onClick={runCapacityAnalysis}
                className="w-full bg-indigo-600 text-white py-3 rounded-xl font-bold hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-indigo-200 transition-all flex flex-col items-center justify-center gap-1"
              >
                {isCalculating ? (
                  <div className="w-full flex flex-col items-center">
                    <div className="flex items-center gap-2">
                       <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> 
                       <span>Calculando... {capacityProgress}%</span>
                    </div>
                    <div className="w-full h-1 bg-white/20 mt-2 rounded-full overflow-hidden">
                       <div className="h-full bg-white transition-all duration-300" style={{ width: `${capacityProgress}%` }}></div>
                    </div>
                  </div>
                ) : (
                  <span className="flex items-center gap-2"><Calculator size={18} /> Iniciar Dimensionamiento</span>
                )
              }
              </button>
              {isCalculating && (
                <p className="text-[10px] text-slate-500 text-center animate-pulse">{capacityStatus}</p>
              )}
            </div>
          </div>
        </div>

        <div className="lg:col-span-2">
          {result && result.summary && (
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden animate-in fade-in slide-in-from-right-4 duration-500">
               <div className="bg-indigo-600 p-8 text-white">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-indigo-100 text-xs font-bold uppercase tracking-widest mb-1">Resultado del Dimensionamiento</p>
                      <h2 className="text-4xl font-black tracking-tighter">
                        {result.summary.personasRequeridas !== undefined 
                          ? `Se requieren ${result.summary.personasRequeridas} personas`
                          : `Cálculo Completado`}
                      </h2>
                    </div>
                    <div className="bg-white/20 p-3 rounded-xl backdrop-blur-md">
                      <Calculator size={32} />
                    </div>
                  </div>
                  <div className="mt-8 grid grid-cols-3 gap-6 border-t border-white/10 pt-6">
                    <div>
                      <p className="text-[10px] font-bold text-indigo-200 uppercase mb-1">Cobertura</p>
                      <p className="text-xl font-bold">{result.summary.cobertura?.toFixed(1)}%</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-bold text-indigo-200 uppercase mb-1">Rutas Semanales</p>
                      <p className="text-xl font-bold">{result.summary.totalRutas}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-bold text-indigo-200 uppercase mb-1">Horas Totales</p>
                      <p className="text-xl font-bold">{result.summary.totalHoras?.toFixed(0)}h</p>
                    </div>
                  </div>
               </div>
               <div className="p-8 space-y-6">
                  {result.omitidos && result.omitidos.length > 0 && (
                    <div className="p-4 bg-amber-50 border border-amber-100 rounded-xl flex gap-3 text-amber-800 text-xs">
                      <AlertCircle size={16} className="shrink-0 text-amber-500" />
                      <div>
                        <p className="font-bold mb-1">{result.omitidos.length} PDVs fueron omitidos</p>
                        <p>Algunos puntos no pudieron ser visitados debido a restricciones de tiempo o distancia (Max Traslado: {rules.maxRelocalizacionMin} min).</p>
                      </div>
                    </div>
                  )}
                  <div className="flex items-center gap-4 p-4 bg-slate-50 rounded-xl border border-slate-100">
                    <Info size={20} className="text-indigo-500 shrink-0" />
                    <p className="text-sm text-slate-600 leading-relaxed italic">
                      "Este cálculo contempla la optimización geográfica real punto a punto utilizando OSRM. Las rutas resultantes han sido particionadas para no exceder las {rules.maxHorasSemanales}h semanales por recurso."
                    </p>
                  </div>
                  <div className="flex gap-4">
                    <button 
                      onClick={() => setActiveTab('maps')}
                      className="flex-1 bg-slate-900 text-white py-4 rounded-xl font-bold hover:bg-slate-800 transition-all flex items-center justify-center gap-2"
                    >
                      <MapIcon size={18} /> Ver Rutas Sugeridas
                    </button>
                    <button 
                      onClick={() => setActiveTab('dashboard')}
                      className="flex-1 border border-slate-200 text-slate-700 py-4 rounded-xl font-bold hover:bg-slate-50 transition-all flex items-center justify-center gap-2"
                    >
                      <BarChart3 size={18} /> Ver Métricas de Costo
                    </button>
                  </div>
               </div>
            </div>
          )}
          {!data && !result && (
            <div className="h-full min-h-[400px] bg-white rounded-2xl border border-slate-200 border-dashed flex flex-col items-center justify-center text-slate-400 text-center p-12">
              <Calculator size={48} className="mb-4 opacity-20" />
              <p className="font-bold text-slate-600">Espera de datos...</p>
              <p className="text-xs max-w-xs mt-2">Sube tu archivo de preventa para calcular la cantidad óptima de personas necesarias para cubrir la operación.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
