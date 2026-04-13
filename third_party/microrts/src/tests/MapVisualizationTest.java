 /*
 * To change this template, choose Tools | Templates
 * and open the template in the editor.
 */
package tests;

import gui.PhysicalGameStatePanel;

import java.awt.*;
import java.io.OutputStreamWriter;
import javax.swing.*;

import gui.frontend.GameController;
import rts.GameState;
import rts.PartiallyObservableGameState;
import rts.PhysicalGameState;
import rts.units.UnitTypeTable;
import util.XMLWriter;
import ai.evaluation.SimpleEvaluationFunction;
import rts.GameState;
import rts.PhysicalGameState;
import rts.units.UnitTypeTable;

/**
 *
 * @author santi
 */
public class MapVisualizationTest {
    public static void main(String args[]) throws Exception {
        UnitTypeTable utt = new UnitTypeTable();
        PhysicalGameState pgs = PhysicalGameState.load("maps/8x8/basesWorkers8x8Obstacle.xml", utt);

        GameState gs = new GameState(pgs, utt);


        XMLWriter xml = new XMLWriter(new OutputStreamWriter(System.out));
        pgs.toxml(xml);
        xml.flush();

        OutputStreamWriter jsonwriter = new OutputStreamWriter(System.out);
        pgs.toJSON(jsonwriter);
        jsonwriter.flush();
        JFrame frame = new JFrame("MicroRTS with Pass Button");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setLayout(new BorderLayout());


        JFrame w = PhysicalGameStatePanel.newVisualizer(
                gs,                  // your GameState
                640,                        // width
                640,                        // height
                false,                      // don't show visibility
                null, // evaluation function
                PhysicalGameStatePanel.COLORSCHEME_BLACK // color scheme
        );// PhysicalGameStatePanel.newVisualizer(gs,640,640);
        JButton passButton = new JButton("Pass");
        passButton.addActionListener(e -> GameController.togglePause());
        frame.getContentPane().add(passButton, BorderLayout.NORTH);
        JFrame w2 = PhysicalGameStatePanel.newVisualizer(new PartiallyObservableGameState(gs,0),640,640, true);
        JFrame w3 = PhysicalGameStatePanel.newVisualizer(gs,640,640,false,PhysicalGameStatePanel.COLORSCHEME_WHITE);
        
    }    
}
