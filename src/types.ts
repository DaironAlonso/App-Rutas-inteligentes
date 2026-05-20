
export interface BusinessRules {
  horaInicio: string;  // "08:00"
  horaFin: string;     // "18:00"
  almuerzoInicio: string; // "12:00"
  almuerzoFin: string;    // "13:00"
  maxHorasDiarias: number;
  maxHorasSemanales: number;
  permanenciaDefaultMin: number;
  distanciaCaminableKm: number;
  velocidadCaminandoKmh: number;
  velocidadBusKmh: number;
  sabadoActivo: boolean;
  sabadoMaxPdvs: number;
  sabadoPermanenciaFija: number;
  maxRelocalizacionMin: number;
  centroPunto: [number, number];
}

export interface PDV {
  id?: string;
  pdv: string;
  latitud: number;
  longitud: number;
  ruta: string;
  dias: string; // "1,3,5"
  frecuencia: number;
  tiempoVisita: number;
  direccion?: string;
  ciudad?: string;
  departamento?: string;
}

export interface RouteStop {
  pdv: PDV;
  horaLlegada: string;
  horaSalida: string;
  distanciaPreviaKm: number;
  tiempoTrasladoMin: number;
  tipoTransporte: 'pie' | 'bus';
  geometry?: any; // To store routing geometry
}

export interface DailyRoute {
  dia: number; // 1-6
  rutaNombre: string;
  paradas: RouteStop[];
  horasTrabajadas: number;
  kmTotales: number;
  geometriaRaw?: any;
}

export interface ProcessingResult {
  id: string;
  timestamp: string;
  rutas: DailyRoute[];
  omitidos: { pdv: PDV; motivo: string; dia: number }[];
  summary: {
    totalPdvs: number;
    totalRutas: number;
    totalKm: number;
    totalHoras: number;
    cobertura: number;
    personasRequeridas?: number;
  };
}
