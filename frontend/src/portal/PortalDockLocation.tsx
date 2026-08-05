import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { portalApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { PortalLayout, PORTAL_INVALID_LINK_MESSAGE } from "./PortalLayout";
import type { PortalDockLocation as PortalDockLocationType } from "../types/api";

// Same CDN-hosted marker icon workaround as DispatchMap.tsx (Phase 11) --
// Vite doesn't resolve Leaflet's bundled marker images the way webpack did.
const slipIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl:
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

const DEFAULT_ZOOM = 16;

const STATUS_TONE: Record<string, "slate" | "green" | "amber" | "red" | "blue"> = {
  confirmed: "blue",
  checked_in: "green",
};

/**
 * GPS "find my dock" (Phase 17, Area D) -- read-only customer-portal view of
 * the customer's OWN slip location(s). Reuses the react-leaflet/OpenStreetMap
 * pattern from `DispatchMap.tsx` (Phase 11), but this view has no admin
 * controls, no other customers' data, and no full marina map -- it only ever
 * renders what `GET /portal/{token}/dock-locations` returns, which is
 * already scoped server-side to this customer's own confirmed/checked-in
 * reservations (see `app/services/portal.py::list_dock_locations`).
 */
export function PortalDockLocation() {
  const { token } = useParams<{ token: string }>();

  const query = useQuery({
    queryKey: ["portal", token, "dock-locations"],
    queryFn: () => portalApi.dockLocations(token!),
    enabled: !!token,
    retry: false,
  });

  return (
    <PortalLayout>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Find my dock</h2>

      {query.isLoading && <Spinner label="Loading your dock location…" />}

      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError && query.error.status === 404
              ? PORTAL_INVALID_LINK_MESSAGE
              : "Something went wrong loading your dock location. Please contact the shop."
          }
        />
      )}

      {query.isSuccess && query.data.length === 0 && (
        <EmptyState message="No GPS location on file for your dock yet. Please contact the shop." />
      )}

      {query.isSuccess && query.data.length > 0 && (
        <div className="flex flex-col gap-4">
          {query.data.map((loc) => (
            <DockLocationCard key={loc.reservation_id} location={loc} />
          ))}
        </div>
      )}
    </PortalLayout>
  );
}

function DockLocationCard({ location }: { location: PortalDockLocationType }) {
  const center: [number, number] = [Number(location.latitude), Number(location.longitude)];

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="font-medium text-slate-900">Slip {location.slip_identifier}</p>
          <p className="text-sm text-slate-500">
            {location.start_date} – {location.end_date}
          </p>
        </div>
        <Badge tone={STATUS_TONE[location.status] ?? "slate"}>{location.status}</Badge>
      </div>
      <div data-testid="dock-location-map">
        <MapContainer
          center={center}
          zoom={DEFAULT_ZOOM}
          style={{ height: "320px", width: "100%" }}
          scrollWheelZoom={false}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <Marker position={center} icon={slipIcon}>
            <Popup>
              <strong>Slip {location.slip_identifier}</strong>
            </Popup>
          </Marker>
        </MapContainer>
      </div>
    </Card>
  );
}
