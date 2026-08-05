import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Customer, Job, TechnicianLocation } from "../types/api";

// Leaflet's default marker icons are shipped as separate image files and
// Vite doesn't resolve them the way webpack's file-loader did, so the
// default L.Icon.Default ends up broken (missing marker images) unless we
// point it at CDN-hosted copies of the same icon set. This mirrors the
// standard react-leaflet workaround; no API key needed since these are
// static assets, not a mapping API call.
const technicianIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl:
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

const jobIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl:
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [16, 26],
  iconAnchor: [8, 26],
  popupAnchor: [1, -22],
  className: "harboriq-job-marker",
});

// Sarasota/Bradenton, FL -- a sane default center when nothing has
// coordinates yet, so the map isn't stranded at (0, 0) in the Gulf of Guinea.
const DEFAULT_CENTER: [number, number] = [27.3364, -82.5307];
const DEFAULT_ZOOM = 11;

export interface DispatchMapProps {
  technicianLocations: TechnicianLocation[];
  jobs: Job[];
  customersById: Map<string, Customer>;
}

/**
 * Free OpenStreetMap tiles via Leaflet -- no API key, no billing account.
 * Shows technician positions (live ping if available, else static home
 * base -- see `TechnicianLocation.is_live`) and job/customer locations
 * (Phase 10 geocoded coordinates).
 */
export function DispatchMap({
  technicianLocations,
  jobs,
  customersById,
}: DispatchMapProps) {
  const techPoints = technicianLocations.filter(
    (t) => t.latitude != null && t.longitude != null,
  );
  const jobPoints = jobs
    .map((job) => ({ job, customer: customersById.get(job.customer_id) }))
    .filter(
      (jp): jp is { job: Job; customer: Customer } =>
        !!jp.customer &&
        jp.customer.latitude != null &&
        jp.customer.longitude != null,
    );

  const center =
    techPoints[0] != null
      ? ([Number(techPoints[0].latitude), Number(techPoints[0].longitude)] as [
          number,
          number,
        ])
      : jobPoints[0] != null
        ? ([
            Number(jobPoints[0].customer.latitude),
            Number(jobPoints[0].customer.longitude),
          ] as [number, number])
        : DEFAULT_CENTER;

  return (
    <div data-testid="dispatch-map">
      <MapContainer
        center={center}
        zoom={DEFAULT_ZOOM}
        style={{ height: "420px", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {techPoints.map((t) => (
          <Marker
            key={t.id}
            position={[Number(t.latitude), Number(t.longitude)]}
            icon={technicianIcon}
          >
            <Popup>
              <strong>{t.full_name ?? "Technician"}</strong>
              <br />
              {t.is_live ? "Live location" : "Home base (no ping yet)"}
              {t.location_updated_at && (
                <>
                  <br />
                  {new Date(t.location_updated_at).toLocaleString()}
                </>
              )}
            </Popup>
          </Marker>
        ))}
        {jobPoints.map(({ job, customer }) => (
          <Marker
            key={job.id}
            position={[Number(customer.latitude), Number(customer.longitude)]}
            icon={jobIcon}
          >
            <Popup>
              <strong>{job.title}</strong>
              <br />
              {[customer.first_name, customer.last_name]
                .filter(Boolean)
                .join(" ") ||
                customer.company_name ||
                "Customer"}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
