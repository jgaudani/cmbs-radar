// A thin React wrapper over ECharts. Only the chart types and components
// used here are registered, which keeps the bundle small.
import { BarChart, LineChart, SankeyChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([BarChart, LineChart, SankeyChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

export type ChartOption = echarts.EChartsCoreOption;
export interface ChartClick { seriesId?: string; seriesName?: string; name: string; dataType?: string; data: unknown }

interface Props {
  option: ChartOption;
  height: number;
  label: string; // accessible name
  onClick?: (e: ChartClick) => void;
}

export function Chart({ option, height, label, onClick }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const click = useRef(onClick);
  click.current = onClick;

  useEffect(() => {
    const c = echarts.init(el.current!, undefined, { renderer: "canvas" });
    chart.current = c;
    c.on("click", (e) => click.current?.(e as unknown as ChartClick));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current!);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={el} role="img" aria-label={label} style={{ height, width: "100%", cursor: onClick ? "pointer" : undefined }} />;
}
