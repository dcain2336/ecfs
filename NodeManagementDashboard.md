# Node Management Dashboard

This repository contains the full implementation code for a Node Management Dashboard. The dashboard supports the following functionalities:

- Node visualization on a map, including status, type, location, and real-time updates.
- Access to node sensors, cameras, and microphones.
- Ability to send messages to nodes.
- Network health monitoring: latency, uptime, etc.

---

## **Frontend (React.js)**

### `NodeCard` Component
```javascript
import React from 'react';

const NodeCard = ({ node, onSendMessage, onAccessSensor, onAccessCamera, onAccessMic }) => {
  const handleSendMessage = () => {
    const message = prompt(`Send a message to ${node.name}:`);
    onSendMessage(node.id, message);
  };

  return (
    <div className="node-card">
      <h3>{node.name}</h3>
      <p>Location: {node.location}</p>
      <p>Type: {node.type}</p>
      <p>Status: {node.status}</p>
      <button onClick={handleSendMessage}>Send Message</button>
      <button onClick={() => onAccessSensor(node.id)}>View Sensor Data</button>
      <button onClick={() => onAccessCamera(node.id)}>Access Camera</button>
      <button onClick={() => onAccessMic(node.id)}>Access Microphone</button>
    </div>
  );
};

export default NodeCard;
```

---

### `Dashboard` Component
```javascript
import React, { useState, useEffect } from 'react';
import NodeCard from './NodeCard';
import NodesMap from './NodesMap';

const Dashboard = () => {
  const [nodes, setNodes] = useState([]);
  const [networkHealth, setNetworkHealth] = useState({});

  useEffect(() => {
    // Fetch node and network data from backend
    fetch('/api/nodes')
      .then(response => response.json())
      .then(data => setNodes(data));

    fetch('/api/network-health')
      .then(response => response.json())
      .then(data => setNetworkHealth(data));
  }, []);

  const sendMessage = (nodeId, message) => {
    fetch(`/api/nodes/${nodeId}/send-message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
  };

  const handleAccessSensor = (nodeId) => {
    fetch(`/api/nodes/${nodeId}/sensor-data`)
      .then(response => response.json())
      .then(data => console.log('Sensor Data: ', data));
  };

  const handleAccessCamera = (nodeId) => {
    window.open(`/api/nodes/${nodeId}/camera-feed`, '_blank');
  };

  const handleAccessMic = (nodeId) => {
    window.open(`/api/nodes/${nodeId}/microphone-feed`, '_blank');
  };

  return (
    <div>
      <h1>System Dashboard</h1>
      <h2>Network Health</h2>
      <p>Latency: {networkHealth.latency}ms</p>
      <p>Uptime: {networkHealth.uptime}%</p>

      <h2>Node Locations</h2>
      <NodesMap nodes={nodes} />

      <h2>Nodes</h2>
      <div className="nodes-container">
        {nodes.map(node => (
          <NodeCard
            key={node.id}
            node={node}
            onSendMessage={sendMessage}
            onAccessSensor={handleAccessSensor}
            onAccessCamera={handleAccessCamera}
            onAccessMic={handleAccessMic}
          />
        ))}
      </div>
    </div>
  );
};

export default Dashboard;
```

---

### `NodesMap` Component
```javascript
import React from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';

const NodesMap = ({ nodes }) => (
  <MapContainer center={[51.505, -0.09]} zoom={2} style={{ height: '400px', width: '100%' }}>
    <TileLayer
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    />
    {nodes.map((node) => (
      <Marker key={node.id} position={[node.latitude, node.longitude]}>
        <Popup>
          <b>{node.name} - {node.type}</b>
          <br />
          <p>{node.location}</p>
        </Popup>
      </Marker>
    ))}
  </MapContainer>
);

export default NodesMap;
```

---

### CSS Styling
```css
body {
  font-family: Arial, sans-serif;
  margin: 0;
  padding: 0;
}

h1 {
  text-align: center;
  background-color: #282c34;
  color: white;
  padding: 20px;
}

.nodes-container {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  padding: 20px;
}

.node-card {
  border: 1px solid #ccc;
  border-radius: 8px;
  padding: 16px;
  width: 200px;
  box-shadow: 2px 2px 8px rgba(0, 0, 0, 0.1);
}

.node-card button {
  background-color: #007bff;
  color: white;
  border: none;
  padding: 8px;
  margin: 5px 0;
  border-radius: 4px;
  cursor: pointer;
}

.node-card button:hover {
  background-color: #0056b3;
}

#map {
  height: 400px;
  width: 100%;
  margin: 20px 0;
}
```

---

## **Backend (Node.js)**

### Express Server Setup
```javascript
const express = require('express');
const app = express();
const ws = require('ws');

app.use(express.json());

// Dummy data for nodes
const nodes = [
  { id: 1, name: 'Node 1', location: 'New York', type: 'Sensor', status: 'Active', latitude: 40.7128, longitude: -74.0060 },
  { id: 2, name: 'Node 2', location: 'Paris', type: 'Camera', status: 'Active', latitude: 48.8566, longitude: 2.3522 },
  { id: 3, name: 'Node 3', location: 'Tokyo', type: 'Microphone', status: 'Inactive', latitude: 35.6895, longitude: 139.6917 },
];

// API Endpoints
app.get('/api/nodes', (req, res) => {
  res.json(nodes);
});

app.get('/api/network-health', (req, res) => {
  res.json({ latency: 50, uptime: 99.9 });
});

app.post('/api/nodes/:id/send-message', (req, res) => {
  const { id } = req.params;
  const { message } = req.body;
  console.log(`Message sent to Node ${id}: ${message}`);
  res.status(200).send('Message sent');
});

app.get('/api/nodes/:id/sensor-data', (req, res) => {
  res.json({ temperature: '22C', humidity: '60%' });
});

app.get('/api/nodes/:id/camera-feed', (req, res) => {
  res.redirect('http://example.com/your-camera-stream'); // Placeholder camera URL
});

app.get('/api/nodes/:id/microphone-feed', (req, res) => {
  res.redirect('http://example.com/your-microphone-stream'); // Placeholder microphone URL
});

// WebSocket for real-time updates
const wss = new ws.Server({ noServer: true });
wss.on('connection', (socket) => {
  console.log('Client connected');
  setInterval(() => {
    socket.send(JSON.stringify(nodes));
  }, 5000);
});

// Start the server
const server = app.listen(5000, () => console.log('API is running at http://localhost:5000'));

// Attach WebSocket to the server
server.on('upgrade', (req, socket, head) => {
  wss.handleUpgrade(req, socket, head, (ws) => {
    wss.emit('connection', ws, req);
  });
});
```

---

## **How to Run**

1. Clone the repository.
2. Start the backend:
   ```bash
   cd backend
   npm install
   node server.js
   ```
3. Start the React frontend:
   ```bash
   cd frontend
   npm install
   npm start
   ```