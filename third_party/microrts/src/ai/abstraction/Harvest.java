/*
 * To change this template, choose Tools | Templates
 * and open the template in the editor.
 */
package ai.abstraction;

import ai.abstraction.pathfinding.PathFinding;
import rts.GameState;
import rts.PhysicalGameState;
import rts.ResourceUsage;
import rts.UnitAction;
import rts.units.Unit;
import util.XMLWriter;

/**
 *
 * @author santi
 */
public class Harvest extends AbstractAction  {
    Unit target;
    Unit base;
    PathFinding pf;
    
    public Harvest(Unit u, Unit a_target, Unit a_base, PathFinding a_pf) {
        super(u);
        target = a_target;
        base = a_base;
        pf = a_pf;
    }
    
    
    public Unit getTarget() {
        return target;
    }
    
    
    public Unit getBase() {
        return base;
    }
    
    
    public boolean completed(GameState gs) {
        if (unit.getResources() > 0) {
            return !gs.getPhysicalGameState().getUnits().contains(base);
        } else {
            return !gs.getPhysicalGameState().getUnits().contains(target);
        }
    }
    
    
    public boolean equals(Object o)
    {
        if (!(o instanceof Harvest)) return false;
        Harvest a = (Harvest)o;
        if (target == null && a.target != null) return false;
        if (target != null && a.target == null) return false;
        if (target != null && target.getID() != a.target.getID()) return false;

        if (base == null && a.base != null) return false;
        if (base != null && a.base == null) return false;
        if (base != null && base.getID() != a.base.getID()) return false;
        return pf.getClass() == a.pf.getClass();
    }
    

    public void toxml(XMLWriter w)
    {
        w.tagWithAttributes("Harvest","unitID=\""+unit.getID()+"\" target=\""+target.getID()+"\" base=\""+base.getID()+"\" pathfinding=\""+pf.getClass().getSimpleName()+"\"");
        w.tag("/Harvest");
    }
     // this is the original method re comment this and don't make changes to they original game
     /**
    public UnitAction execute(GameState gs, ResourceUsage ru) {
        System.out.println(" inside Harevest class 73  gmu3r2g : ");

        if (unit.getResources() == 0) {
            System.out.println("Moving toward resource at: (" + target.getX() + "," + target.getY() + ")");
        } else {
            System.out.println("Returning to base at: (" + base.getX() + "," + base.getY() + ")");
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        System.out.println("Executing Harvest for unit: " + unit);
        if (unit.getResources()==0) {
            if (target == null) return null;
            // go get resources:
//            System.out.println("findPathToAdjacentPosition from Harvest: (" + target.getX() + "," + target.getY() + ")");
            UnitAction move = pf.findPathToAdjacentPosition(unit, target.getX()+target.getY()*gs.getPhysicalGameState().getWidth(), gs, ru);
            if (move!=null) {
                if (gs.isUnitActionAllowed(unit, move)) return move;
                return null;
            }

            // harvest:
            if (target.getX() == unit.getX() &&
                target.getY() == unit.getY()-1) return new UnitAction(UnitAction.TYPE_HARVEST,UnitAction.DIRECTION_UP);
            if (target.getX() == unit.getX()+1 &&
                target.getY() == unit.getY()) return new UnitAction(UnitAction.TYPE_HARVEST,UnitAction.DIRECTION_RIGHT);
            if (target.getX() == unit.getX() &&
                target.getY() == unit.getY()+1) return new UnitAction(UnitAction.TYPE_HARVEST,UnitAction.DIRECTION_DOWN);
            if (target.getX() == unit.getX()-1 &&
                target.getY() == unit.getY()) return new UnitAction(UnitAction.TYPE_HARVEST,UnitAction.DIRECTION_LEFT);
        } else {
            // return resources:
            if (base == null) return null;
//            System.out.println("findPathToAdjacentPosition from Return: (" + target.getX() + "," + target.getY() + ")");
            UnitAction move = pf.findPathToAdjacentPosition(unit, base.getX()+base.getY()*gs.getPhysicalGameState().getWidth(), gs, ru);
            if (move!=null) {
                if (gs.isUnitActionAllowed(unit, move)) return move;
                return null;
            }

            // harvest:
            if (base.getX() == unit.getX() &&
                base.getY() == unit.getY()-1) return new UnitAction(UnitAction.TYPE_RETURN,UnitAction.DIRECTION_UP);
            if (base.getX() == unit.getX()+1 &&
                base.getY() == unit.getY()) return new UnitAction(UnitAction.TYPE_RETURN,UnitAction.DIRECTION_RIGHT);
            if (base.getX() == unit.getX() &&
                base.getY() == unit.getY()+1) return new UnitAction(UnitAction.TYPE_RETURN,UnitAction.DIRECTION_DOWN);
            if (base.getX() == unit.getX()-1 &&
                base.getY() == unit.getY()) return new UnitAction(UnitAction.TYPE_RETURN,UnitAction.DIRECTION_LEFT);
        }
        return null;
    }    */
     public UnitAction execute(GameState gs, ResourceUsage ru) {
         System.out.println("🟡 inside Harvest class : gmu3r2g");

         PhysicalGameState pgs = gs.getPhysicalGameState();
         System.out.println("🎯 Executing Harvest for unit: " + unit);
         // ✅ Track full harvest cycle:
         System.out.println("Resources carried: " + unit.getResources());
         System.out.println("Current position: (" + unit.getX() + "," + unit.getY() + ")");
         System.out.println("Target: (" + target.getX() + "," + target.getY() + "), Base: (" + base.getX() + "," + base.getY() + ")");


         UnitAction moveOrAction = null;

         if (unit.getResources() == 0) {
             if (target == null) {
                 System.out.println("❌ No target resource found.");
                 return null;
             }

             System.out.println("➡️ Moving toward resource at: (" + target.getX() + "," + target.getY() + ")");

             moveOrAction = pf.findPathToAdjacentPosition( // pathfinder Astar
                     unit,
                     target.getX() + target.getY() * pgs.getWidth(),
                     gs,
                     ru
             );

             if (moveOrAction != null && gs.isUnitActionAllowed(unit, moveOrAction)) {
                 System.out.println("✅ Returned UnitAction (move to resource): " + moveOrAction);
                 return moveOrAction;
             }

             // Adjacent? Then HARVEST
             if (target.getX() == unit.getX() && target.getY() == unit.getY() - 1){
                 System.out.println("✅ Directly adjacent to resource, issuing HARVEST action.");
                 moveOrAction = new UnitAction(UnitAction.TYPE_HARVEST, UnitAction.DIRECTION_UP);
             }
             else if (target.getX() == unit.getX() + 1 && target.getY() == unit.getY()){
                 System.out.println(" 164  in second block ");
                 moveOrAction = new UnitAction(UnitAction.TYPE_HARVEST, UnitAction.DIRECTION_RIGHT);
             }
             else if (target.getX() == unit.getX() && target.getY() == unit.getY() + 1){
                 System.out.println(" 168  in 3rd block ");
                 moveOrAction = new UnitAction(UnitAction.TYPE_HARVEST, UnitAction.DIRECTION_DOWN); }
             else if (target.getX() == unit.getX() - 1 && target.getY() == unit.getY()){
                 System.out.println(" 171  in 4rd block ");
                 moveOrAction = new UnitAction(UnitAction.TYPE_HARVEST, UnitAction.DIRECTION_LEFT); }

         } else {
             if (base == null) {
                 System.out.println("❌ No base found to return resources.");
                 return null;
             }

             System.out.println("⬅️ Returning to base at: (" + base.getX() + "," + base.getY() + ")");

             moveOrAction = pf.findPathToAdjacentPosition(
                     unit,
                     base.getX() + base.getY() * pgs.getWidth(),
                     gs,
                     ru
             );
             if (moveOrAction == null) {
                 System.out.println("⚠️  issue in they findPathToAdjacentPosition No path to adjacent cell of resource found. May be blocked or unreachable.");
             }

             if (moveOrAction != null && gs.isUnitActionAllowed(unit, moveOrAction)) {
                 System.out.println("✅ Returned UnitAction (move to base): " + moveOrAction);
                 return moveOrAction;
             }

             // Adjacent? Then RETURN
             if (base.getX() == unit.getX() && base.getY() == unit.getY() - 1)
                 moveOrAction = new UnitAction(UnitAction.TYPE_RETURN, UnitAction.DIRECTION_UP);
             else if (base.getX() == unit.getX() + 1 && base.getY() == unit.getY())
                 moveOrAction = new UnitAction(UnitAction.TYPE_RETURN, UnitAction.DIRECTION_RIGHT);
             else if (base.getX() == unit.getX() && base.getY() == unit.getY() + 1)
                 moveOrAction = new UnitAction(UnitAction.TYPE_RETURN, UnitAction.DIRECTION_DOWN);
             else if (base.getX() == unit.getX() - 1 && base.getY() == unit.getY())
                 moveOrAction = new UnitAction(UnitAction.TYPE_RETURN, UnitAction.DIRECTION_LEFT);
         }

         System.out.println("📤 Returned Final UnitAction: " + moveOrAction); // it is returning null may be i need to add A* pathfinder and pathfinding algorithum hear
         return moveOrAction;
     }


}
