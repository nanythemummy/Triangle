import Metashape
import math

#compatibility check.
lowestversion = 2.0
versionused = ".".join(Metashape.app.version.split('.')[:2]) #Not sure why agisoft wants me to split on . and rejoin on it.
if float(versionused) <= lowestversion:
    raise Exception("Incompatible Metashape Version. You have %s, but you need higher than %s" %versionused, str(lowestversion))
doc = Metashape.app.document
chunk = doc.chunk
#Adjust the following to fit your own scale.
TRIANGLE = {
    "type":"12bit",
    "unit":"mm",
    "scalebars":{
        "type":"explicit",
        "bars":[
        {
        "points":[1,2],
        "distance":180,
        "units":"mm"
        },
        {
        "points":[2,3],
        "distance":179,
        "units":"mm"
        },
        {
        "points":[1,3],
        "distance":254,
        "units":"mm"
        }
        ],
        "axes":{
                "xpos":[2,3],
                "xneg":[],
                "zpos":[2,1],
                "zneg":[]
            }
    }
}
#Adding this so people can use different marker types with their triangles.
targetTypes = {
    "Circular":Metashape.TargetType.CircularTarget,
    "12bit":Metashape.TargetType.CircularTarget12bit,
    "14bit":Metashape.TargetType.CircularTarget14bit,
    "16bit":Metashape.TargetType.CircularTarget16bit,
    "20bit":Metashape.TargetType.CircularTarget20bit,
    "Cross":Metashape.TargetType.CrossTarget
}
def detect_targets()->bool:
    #I'm not terribly sure this is needed. These three lines were borrowed from someone else's code.
    #I'm not sure  the point of arbitrarily setting this when photos might not be yet aligned.
    chunk.tiepoint_accuracy = 0.25 # pixels WHAT ARE THESE MAGIC NUMBERS?
    chunk.marker_projection_accuracy = 0.5 # pixels
    chunk.marker_location_accuracy = Metashape.Vector( (5.0e-5, 5.0e-5, 5.0e-5) ) # meters (= 0.05 mm)
    
    print("Detecting Scalebars.")
    templist = [p['points'] for p in TRIANGLE["scalebars"]["bars"]]
    markerlist = list(set(f"target {pt}" for sublist in templist for pt in sublist))
    for m in chunk.markers:
         if m.label in markerlist:
              print(f"Removing Chunk {m.label}")
              chunk.remove(m)
    chunk.detectMarkers(target_type = targetTypes[TRIANGLE["type"]], filter_mask = False)
    if len(chunk.markers)==0:
         print("No Markers Found.")
         return False
    else:
         print("Found %s markers", len(chunk.markers))
    chunk.refineMarkers()
    return True

def get_numbered_target(targetnumber:int)->Metashape.Marker:
    #this assumes that each of the target markers have unique names. 
    #If they don't, it's going to return the first one with the name that it finds.
    #this may cause unexpected results, which should be resolved by deleting pre-existing markers
    #with the names of the targets in the function detect_targets

    name = f"target {targetnumber}"
    desiredmarker = None
    for marker in chunk.markers:
            if marker.label ==name:
                desiredmarker = marker
                break
    return desiredmarker

def convert_unit_to_meters(unit:str,val:float)->float:
    """Takes an input value and a unit and converts that value to meters based on unit.
    
    Parameters:
    -----------
    unit: string: either cm, mm, or km
    val: the falue to convert.
    
    returns a float of the converted value.
    """
    unit = str.lower(unit)
    if unit == "cm":
        return val*0.01
    elif unit == "mm":
        return val*0.001
    elif unit == "km":
        return val*100.0
    else:
        return val*1.0
    
def set_scalebars():
    for definition in TRIANGLE["scalebars"]["bars"]:
        marker1 = get_numbered_target(definition['points'][0])
        marker2 = get_numbered_target(definition['points'][1])
        if marker1 and marker2:
            #either make a new scalebar or find one that already exists between the two markers and reset the distance between them.
            scalebar = None
            for existingbar in chunk.scalebars:
                if (existingbar.point0==marker1 or existingbar.point0==marker1) and (existingbar.point0==marker2 or existingbar.point1==marker2):
                    scalebar = existingbar
                    break
            if scalebar is None:
                scalebar = chunk.addScalebar(marker1,marker2)
            scalebar.reference.distance = convert_unit_to_meters(definition["units"],definition["distance"])
            scalebar.reference.accuracy = 1.0e-5
            scalebar.reference.enabled = True
        chunk.updateTransform()

def find_axes_from_markers()->list:
    if not chunk.markers:
        print(f"No markers to align on chunk {chunk.label}.")
        return []
    xaxis = []
    zaxis = []
    expectedaxes = TRIANGLE["scalebars"]["axes"]
    for m in expectedaxes["xpos"]+expectedaxes["xneg"]:
        pt = get_numbered_target(m)
        if not pt.position==None:
            xaxis.append(pt.position)
    for z in expectedaxes["zpos"]+expectedaxes["zneg"]:
        pt = get_numbered_target(z)
        if not pt.position==None:
            zaxis.append(pt.position)
    if len(xaxis)<2 or len(zaxis) <2:
        print("Not enough data to determine x and z axes.")
        return []
    ux = (xaxis[1]-xaxis[0])
    uz = (zaxis[1]-zaxis[0])
    yaxis = Metashape.Vector.cross(uz,ux)
    ux.normalize()
    uz.normalize()
    yaxis.normalize()
    
    #Cross product only guarantees a y-axis perpendicular to the marker plane--it says nothing about
   # this assumes that your markers are facing up and on the same flat surface as the object. 
   # The cameras that can see the marker will necessarily be above the markers so we can use the average
   # position vectors of cameras that can see the markers to figure out of the Y axis ends up facing 
   # in the wrong direction due to the way the marker numbers were fed into the above configuration.

    markernumbers = set(pt for bar in TRIANGLE["scalebars"]["bars"] for pt in bar["points"])
    observing_cameras = set()
    for markernum in markernumbers:
        tm = get_numbered_target(markernum)
        if tm is not None:
            observing_cameras.update(tm.projections.keys())
    cam_positions = [cam.center for cam in observing_cameras if cam.center]
    if cam_positions:
        origin = xaxis[0]  #marker 2, the shared vertex of the x and z axis definitions.
        avg_cam = sum(cam_positions, Metashape.Vector([0,0,0])) * (1.0/len(cam_positions))
        toward_cameras = avg_cam - origin
        toward_cameras.normalize()
        if yaxis * toward_cameras < 0:
            print("y-axis pointed away from the cameras (i.e. into the table)--flipping it.")
            yaxis = -yaxis
    else:
        print("WARNING: no aligned cameras to check y-axis direction against--sign is not verified.")
    axes = [ux,yaxis,uz]
    print(f"returning axes {axes}")
    return axes

def reorient_on_plane()->bool:
    scalemod = 1.0
    axes = find_axes_from_markers()
    if len(axes)>0:
        print("Reorienting model on axes.")
        transmat = chunk.transform.matrix
        scale = math.sqrt(transmat[0,0]**2+transmat[0,1]**2 + transmat[0,2]**2) #length of the top row in the matrix, but why?
        scale*=scalemod 
        scalematrix = Metashape.Matrix().Diag([scale,scale,scale,1])
        newaxes = Metashape.Matrix([[axes[0].x,axes[0].y, axes[0].z,0],
                        [axes[1].x,axes[1].y,axes[1].z,0],
                        [axes[2].x, axes[2].y,axes[2].z,0],
                        [0,0,0,1]])
        chunk.transform.matrix=scalematrix*newaxes 
        return True
    else:
        return False
     
def detect_triangle():
     if detect_targets():
        set_scalebars()
        doc.save()
        reorient_on_plane()
        print("Great success")
    
label = "Scripts/Detect Orientation Triangle"
Metashape.app.addMenuItem(label, detect_triangle)
print("To execute this script press {}".format(label))
