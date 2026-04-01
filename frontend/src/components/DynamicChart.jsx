// src/components/DynamicChart.jsx
// Fully generic chart renderer — reads all field names from viz config.
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend,
} from "recharts";

const PAL = ["#4f8ef7","#3dd68c","#f5a623","#9b7ff4","#f06060","#38bdf8","#fb923c","#a3e635"];

const TT = {
  contentStyle:{ background:"#171b25", border:"1px solid rgba(255,255,255,.07)",
                 borderRadius:6, fontSize:12, color:"#e8ecf2" },
  itemStyle:{ color:"#8b92a5" },
  labelStyle:{ color:"#e8ecf2", fontWeight:600 },
};

const fmtVal = (v, fmt) => {
  try {
    const f = parseFloat(v);
    if (fmt === "percent") return `${(f*100).toFixed(1)}%`;
    if (Number.isInteger(f)) return f.toLocaleString();
    return f.toFixed(2);
  } catch(_){ return v; }
};

function XTick({ x, y, payload }) {
  const s = String(payload?.value ?? "");
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={12} textAnchor="middle" fill="#545c70" fontSize={10}>
        {s.length > 11 ? s.slice(0,11)+"…" : s}
      </text>
    </g>
  );
}

function PieLabel({ cx,cy,midAngle,innerRadius,outerRadius,percent }) {
  if (percent < 0.05) return null;
  const R = Math.PI/180;
  const r = innerRadius+(outerRadius-innerRadius)*0.55;
  return (
    <text x={cx+r*Math.cos(-midAngle*R)} y={cy+r*Math.sin(-midAngle*R)}
          fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={11}>
      {`${(percent*100).toFixed(0)}%`}
    </text>
  );
}

function NoData() { return <div className="chart-no-data">No data available</div>; }

export default function DynamicChart({ viz }) {
  if (!viz) return <NoData />;
  const { chart_type, data=[], x_field, y_field, label_field, value_field, y_format="number" } = viz;
  if (!data.length) return <NoData />;

  const fmt = (v) => fmtVal(v, y_format);
  const customTT = { ...TT, formatter: fmt };

  if (chart_type === "bar") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{top:4,right:8,left:0,bottom:20}}>
          <CartesianGrid strokeDasharray="3 3" vertical={false}/>
          <XAxis dataKey={x_field} tick={<XTick/>} interval={0}/>
          <YAxis tick={{fill:"#545c70",fontSize:10}} width={44} tickFormatter={fmt}/>
          <Tooltip {...TT} formatter={fmt}/>
          <Bar dataKey={y_field} radius={[3,3,0,0]}>
            {data.map((_,i)=><Cell key={i} fill={PAL[i%PAL.length]}/>)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "horizontal_bar") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={Math.max(200,data.length*34)}>
        <BarChart layout="vertical" data={data} margin={{top:4,right:8,left:100,bottom:4}}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false}/>
          <XAxis type="number" tick={{fill:"#545c70",fontSize:10}} tickFormatter={fmt}/>
          <YAxis type="category" dataKey={x_field} tick={{fill:"#8b92a5",fontSize:11}}
                 width={95} tickFormatter={v=>String(v??"").slice(0,16)}/>
          <Tooltip {...TT} formatter={fmt}/>
          <Bar dataKey={y_field} radius={[0,3,3,0]}>
            {data.map((_,i)=><Cell key={i} fill={PAL[i%PAL.length]}/>)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "line") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{top:4,right:8,left:0,bottom:20}}>
          <CartesianGrid strokeDasharray="3 3" vertical={false}/>
          <XAxis dataKey={x_field} tick={<XTick/>} interval="preserveStartEnd"/>
          <YAxis tick={{fill:"#545c70",fontSize:10}} width={44} tickFormatter={fmt}/>
          <Tooltip {...TT} formatter={fmt}/>
          <Line type="monotone" dataKey={y_field} stroke={PAL[0]} strokeWidth={2}
                dot={{fill:PAL[0],r:3}} activeDot={{r:5}}/>
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "histogram") {
    const xk = x_field || "range";
    const yk = y_field || "count";
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{top:4,right:8,left:0,bottom:20}}>
          <CartesianGrid strokeDasharray="3 3" vertical={false}/>
          <XAxis dataKey={xk} tick={<XTick/>} interval={0}/>
          <YAxis tick={{fill:"#545c70",fontSize:10}} width={44}/>
          <Tooltip {...TT}/>
          <Bar dataKey={yk} fill={PAL[3]} radius={[2,2,0,0]}/>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "pie" || chart_type === "donut") {
    const lf = label_field || x_field;
    const vf = value_field || y_field;
    if (!lf || !vf) return <NoData />;
    const inner = chart_type === "donut" ? 55 : 0;
    return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={data} dataKey={vf} nameKey={lf} cx="50%" cy="50%"
               outerRadius={95} innerRadius={inner} labelLine={false} label={<PieLabel/>}>
            {data.map((_,i)=><Cell key={i} fill={PAL[i%PAL.length]}/>)}
          </Pie>
          <Tooltip {...TT} formatter={fmt}/>
          <Legend iconSize={10} wrapperStyle={{fontSize:11,color:"#8b92a5"}}
                  formatter={v=>String(v??"").slice(0,18)}/>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chart_type === "kpi_card") {
    return (
      <div className="kpi-card-grid">
        {data.map((item,i)=>(
          <div key={i} className="kpi-item">
            <span className="kpi-label">{item.metric ?? `Stat ${i+1}`}</span>
            <span className="kpi-value">
              {typeof item.value === "number"
                ? fmt(item.value)
                : (item.value ?? "—")}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return <NoData />;
}