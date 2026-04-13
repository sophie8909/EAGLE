/*
 * To change this template, choose Tools | Templates
 * and open the template in the editor.
 */
package gui;

import javax.swing.*;

import gui.frontend.GameController;
import rts.GameState;

import java.awt.*;

/**
 *
 * @author santi
 */
public class PhysicalGameStateJFrame extends JFrame {
    PhysicalGameStatePanel panel;
    /**
    public PhysicalGameStateJFrame(String title, int width, int height, PhysicalGameStatePanel panel) {
        super(title);

        setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        setSize(width, height);

        // ✅ Create Pass button
        JButton passButton = new JButton("Pass");
        passButton.addActionListener(e -> GameController.togglePause());

        // ✅ Create top panel and add button
        JPanel topPanel = new JPanel(new BorderLayout());
        topPanel.add(passButton, BorderLayout.NORTH);

        // ✅ Set layout and add components
        getContentPane().setLayout(new BorderLayout());
        getContentPane().add(topPanel, BorderLayout.NORTH);   // add Pass button
        getContentPane().add(panel, BorderLayout.CENTER);     // main game panel

        setVisible(true);
    } */


    public PhysicalGameStateJFrame(String title, int dx, int dy, PhysicalGameStatePanel a_panel) {
        super(title);
        panel = a_panel;

        getContentPane().add(panel);
        pack();
        setResizable(false);
        setSize(dx,dy);
        setVisible(true);
        setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
    }
    
    public PhysicalGameStatePanel getPanel() {
        return panel;
    }
    
    public void setStateCloning(GameState gs) {
        panel.setStateCloning(gs);
    }
            
    public void setStateDirect(GameState gs) {
        panel.setStateDirect(gs);
    }
}
